# Plan: Microbenchmark for vXi8 Splat Multiply Optimization

This plan creates a microbenchmark to measure the performance impact of the vXi8 splat multiply optimization that decomposes 8-bit vector multiplies by constants into shift-add-sub sequences.

## Background

The optimization (in HEAD^ commit) transforms `vXi8 * splat_constant` operations into efficient shift-add-sub sequences:
- **Sum of two powers:** `2^a + 2^b` (e.g., 6 = 4 + 2, 10 = 8 + 2)
- **Difference of two powers:** `2^a - 2^b` (e.g., 6 = 8 - 2, 12 = 16 - 4)

Example transformation for multiply by 6:
```asm
; Before: uses PMULLW (expensive for i8)
; After:
vpaddb %xmm0, %xmm0, %xmm1     ; xmm1 = a * 2
vpsllw $2, %xmm0, %xmm0        ; shift by 2 (word shift)
vpand mask, %xmm0, %xmm0       ; mask off overflow bits
vpaddb %xmm1, %xmm0, %xmm0     ; add the two parts
```

## Approach

- **Framework:** Google Benchmark (LLVM's standard benchmarking framework)
- **Benchmark style:** C++ source compiled with Clang to measure generated assembly performance
- **Comparison method:** Two builds - optimized vs. baseline (revert optimization)
- **Target ISAs:** SSE2, AVX2, AVX-512BW

## Steps

### 1. Create benchmark source file
**File:** `llvm/benchmarks/VectorMulI8Bench.cpp`

Implement a C++ benchmark using Google Benchmark that:
- Exercises v16i8, v32i8, and v64i8 multiply operations
- Uses the target constants covered by the optimization: 6, 10, 12, 18, 20, 24, 34, 36, 40
- Includes negative constant variants: -6, -12
- Prevents compiler from optimizing away results using `benchmark::DoNotOptimize()`

```cpp
#include "benchmark/benchmark.h"
#include <cstdint>
#include <vector>

// Use C++ vector types that Clang will lower to SIMD
typedef int8_t v16i8 __attribute__((vector_size(16)));
typedef int8_t v32i8 __attribute__((vector_size(32)));
typedef int8_t v64i8 __attribute__((vector_size(64)));

static void BM_v16i8_Mul6(benchmark::State &State) {
  v16i8 input = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16};
  for (auto _ : State) {
    v16i8 result = input * 6;
    benchmark::DoNotOptimize(result);
    benchmark::ClobberMemory();
  }
}
BENCHMARK(BM_v16i8_Mul6);

// Similar functions for other constants and vector sizes...

BENCHMARK_MAIN();
```

### 2. Register benchmark in CMake
**File:** `llvm/benchmarks/CMakeLists.txt`

Add the benchmark target:
```cmake
add_benchmark(VectorMulI8Bench VectorMulI8Bench.cpp PARTIAL_SOURCES_INTENDED)
```

Note: This benchmark only requires the `benchmark` library (no LLVM components needed since it measures generated code, not LLVM APIs).

### 3. Implement comprehensive benchmark functions

Cover all combinations:
- **Vector sizes:** v16i8 (SSE2), v32i8 (AVX2), v64i8 (AVX-512BW)
- **Constants:** 6, 10, 12, 18, 20, 24, 34, 36, 40, -6, -12
- **Parameterized benchmarks** for data size scaling

### 4. Manual compilation (recommended)

Since the benchmark uses GCC vector extensions that require Clang (not MSVC), use manual compilation with the built Clang:

#### Windows (with MSVC build of LLVM)

```powershell
# Compile and link the benchmark (from llvm-project root)
.\build\Release\bin\clang-cl.exe /O2 /arch:AVX2 /MD /EHsc `
  -I third-party/benchmark/include `
  llvm/benchmarks/VectorMulI8Bench.cpp `
  build/Release/lib/Release/benchmark.lib Shlwapi.lib `
  -o VectorMulI8Bench.exe

# Run the benchmark
.\VectorMulI8Bench.exe

# Run with JSON output for comparison
.\VectorMulI8Bench.exe --benchmark_repetitions=5 --benchmark_out=results-opt.json --benchmark_out_format=json
```

#### Linux/macOS

```bash
# Compile and link the benchmark (from llvm-project root)
./build/bin/clang++ -O2 -march=native \
  -I third-party/benchmark/include \
  llvm/benchmarks/VectorMulI8Bench.cpp \
  -Lbuild/lib -lbenchmark -lpthread \
  -o VectorMulI8Bench

# (Might need to build libbenchmark first)
cmake --build build/ --target benchmark

# Run the benchmark
./VectorMulI8Bench

# Run with JSON output for comparison
./VectorMulI8Bench --benchmark_repetitions=5 --benchmark_out=results-opt.json --benchmark_out_format=json
```

### 5. CMake-based build (alternative)

If you want to build via CMake (requires a Clang-based build, not MSVC):

```bash
# Configure with benchmarks enabled
cmake -S llvm -B build -G Ninja \
  -DCMAKE_C_COMPILER=clang \
  -DCMAKE_CXX_COMPILER=clang++ \
  -DLLVM_BUILD_BENCHMARKS=ON \
  -DLLVM_INCLUDE_BENCHMARKS=ON \
  -DCMAKE_BUILD_TYPE=Release

# Build the benchmark
cmake --build build --target VectorMulI8Bench

# Run
./build/bin/VectorMulI8Bench
```

### 6. Baseline comparison methodology

```powershell
# 1. Run optimized benchmark (current HEAD)
.\VectorMulI8Bench.exe --benchmark_repetitions=5 --benchmark_out=results-opt.json --benchmark_out_format=json

# 2. Revert optimization for baseline measurement
git stash  # Save any local changes
git revert --no-commit HEAD^  # Revert the optimization commit

# 3. Rebuild clang-cl (or just llc if only testing via llc)
cmake --build build --config Release --target clang

# 4. Recompile and run baseline benchmark
.\build\Release\bin\clang-cl.exe /O2 /arch:AVX2 /MD /EHsc `
  -I third-party/benchmark/include `
  llvm/benchmarks/VectorMulI8Bench.cpp `
  build/Release/lib/Release/benchmark.lib Shlwapi.lib `
  -o VectorMulI8Bench.exe

.\VectorMulI8Bench.exe --benchmark_repetitions=5 --benchmark_out=results-baseline.json --benchmark_out_format=json

# 5. Restore the optimization
git revert --abort
git stash pop

# 6. Compare results
python third-party/benchmark/tools/compare.py benchmarks results-baseline.json results-opt.json
```

### 7. Validate generated assembly

Before running benchmarks, verify the optimization is applied:

#### Windows
```powershell
# Generate assembly listing
.\build\Release\bin\clang-cl.exe /O2 /arch:AVX2 /FA /c `
  -I third-party/benchmark/include `
  llvm/benchmarks/VectorMulI8Bench.cpp `
  -o VectorMulI8Bench.obj

# Search for multiply instructions in the assembly
Select-String -Path VectorMulI8Bench.asm -Pattern "vpaddb|vpsllw|vpand|vpmullw"
```

#### Linux/macOS
```bash
# Compile to assembly to inspect generated code
./build/bin/clang++ -O2 -march=x86-64-v3 -S \
  -I third-party/benchmark/include \
  llvm/benchmarks/VectorMulI8Bench.cpp -o - | grep -E "vpaddb|vpsllw|vpand|vpmullw"
```

Look for:
- **Optimized:** `vpaddb`, `vpsllw`, `vpand` sequences (shift-add-sub decomposition)
- **Baseline:** `vpmullw` or scalar fallback

## Test Constants Rationale

| Constant | Decomposition | Pattern |
|----------|---------------|---------|
| 6 | 4 + 2 = 2² + 2¹ | sum of powers |
| 10 | 8 + 2 = 2³ + 2¹ | sum of powers |
| 12 | 8 + 4 = 2³ + 2² | sum of powers |
| 18 | 16 + 2 = 2⁴ + 2¹ | sum of powers |
| 20 | 16 + 4 = 2⁴ + 2² | sum of powers |
| 24 | 16 + 8 = 2⁴ + 2³ | sum of powers |
| 34 | 32 + 2 = 2⁵ + 2¹ | sum of powers |
| 36 | 32 + 4 = 2⁵ + 2² | sum of powers |
| 40 | 32 + 8 = 2⁵ + 2³ | sum of powers |
| 6 | 8 - 2 = 2³ - 2¹ | difference (alt) |
| 12 | 16 - 4 = 2⁴ - 2² | difference (alt) |
| -6 | -(4 + 2) | negated sum |
| -12 | -(8 + 4) | negated sum |

## Expected Results

The optimization should show improvement for:
- Operations where `pmullw` (16-bit multiply) + masking is replaced by shifts + adds/subs
- Larger vector sizes (v32i8, v64i8) where the multiply cost is higher
- Constants requiring only 1-2 shifts vs. full multiplication

## Files to Create/Modify

1. **Create:** `llvm/benchmarks/VectorMulI8Bench.cpp`
2. **Modify:** `llvm/benchmarks/CMakeLists.txt` (add benchmark target)

## Implementation Checklist

- [ ] **Step 1: Create benchmark source file**
  - [ ] Create `llvm/benchmarks/VectorMulI8Bench.cpp`
  - [ ] Implement v16i8 benchmark functions for all constants (6, 10, 12, 18, 20, 24, 34, 36, 40, -6, -12)
  - [ ] Implement v32i8 benchmark functions for all constants
  - [ ] Implement v64i8 benchmark functions for all constants
  - [ ] Add `benchmark::DoNotOptimize()` and `benchmark::ClobberMemory()` to prevent dead code elimination

- [ ] **Step 2: Register benchmark in CMake**
  - [ ] Add `add_benchmark(VectorMulI8Bench ...)` to `llvm/benchmarks/CMakeLists.txt`

- [ ] **Step 3: Build optimized version**
  - [ ] Configure with `-DLLVM_BUILD_BENCHMARKS=ON -DLLVM_INCLUDE_BENCHMARKS=ON`
  - [ ] Build `VectorMulI8Bench` target
  - [ ] Run benchmark and save results to `results-opt.json`

- [ ] **Step 4: Build baseline version**
  - [ ] Run `git revert --no-commit <optimization-commit>` to disable the optimization
  - [ ] Rebuild `VectorMulI8Bench` target
  - [ ] Run benchmark and save results to `results-baseline.json`
  - [ ] Run `git revert --abort` or `git checkout HEAD` to restore optimization

- [ ] **Step 5: Compare and analyze results**
  - [ ] Use `compare.py benchmarks results-baseline.json results-opt.json` to compare
  - [ ] Document speedup/regression for each vector size and constant
  - [ ] Validate assembly shows expected instruction sequences

## Notes

- Ensure CPU frequency scaling is disabled for accurate measurements
- Run on hardware with AVX-512 support for v64i8 tests (or skip those tests on older CPUs)
- The benchmark measures end-to-end throughput; for latency analysis, consider using LLVM-MCA
