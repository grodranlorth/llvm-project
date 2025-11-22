## Plan: Add Unit Tests for 8-Bit Vector Multiply Optimization

Add comprehensive lit tests in `llvm/test/CodeGen/X86/` to verify the 8-bit vector multiply constant decomposition optimization transforms `mul` operations into efficient shift-add-sub sequences. Test vector types (v16i8, v32i8, v64i8) with decomposable constants (powers of 2, sum/difference of powers of 2) and non-decomposable edge cases.

**Note:** This optimization only applies to vXi8 vector types, not scalar i8. Scalar i8 multiply optimizations are already handled by existing LLVM infrastructure using LEA instructions.

### Steps

1. **Create `llvm/test/CodeGen/X86/vector-mul-i8-decompose.ll`** for vXi8 vector multiply tests. Add functions for uniform constant vectors testing: v16i8 with constants 3, 5, 7, 9, 15, 17, 31, 33, 63, 65, 127; v32i8 (AVX2) with constants 3, 5, 7, 17, 33; v64i8 (AVX512) with constants 3, 5, 17. Include multiple RUN lines with different target features: `-mattr=+sse2`, `-mattr=+avx2`, `-mattr=+avx512bw`. Verify output uses `psllw`/`vpsllw`, `paddb`/`vpaddb`, `psubb`/`vpsubb` instead of multiplication. Auto-generate CHECK patterns with check-prefixes (SSE2, AVX2, AVX512).

2. **Create `llvm/test/CodeGen/X86/vector-mul-i8-negative.ll`** for negative test cases. Include: non-uniform vectors (mixed constants not all decomposable), large non-decomposable constants (e.g., 11, 13, 19, 23, 29, 37, 41), multiply by 0 and 1 (should optimize differently or fold), non-splat vectors to ensure optimization only applies to uniform constants. Verify these fall back to standard multiply instructions or other existing optimizations.

3. **Add test execution documentation** in a comment block at the top of each test file explaining how to run tests locally: `llvm-lit llvm/test/CodeGen/X86/vector-mul-i8-decompose.ll` for individual test, `llvm-lit llvm/test/CodeGen/X86/` for all X86 tests. Document how to regenerate CHECK lines: `python llvm/utils/update_llc_test_checks.py <test-file>.ll`.

4. **Run and validate tests** from the build directory using `llvm-lit` to ensure all tests pass and verify the optimization is correctly transforming multiply operations. Check both that decomposable constants are optimized AND non-decomposable constants are not incorrectly transformed.

### Implementation Checklist
- [x] Step 1: Create `llvm/test/CodeGen/X86/vector-mul-i8-decompose.ll` with vXi8 vector test functions.
- [x] Step 1a: Add RUN lines for SSE2, AVX2, and AVX512BW targets with appropriate check-prefixes.
- [x] Step 1b: Generate CHECK assertions using `python llvm/utils/update_llc_test_checks.py llvm/test/CodeGen/X86/vector-mul-i8-decompose.ll`.
- [x] Step 1c: Verify vector tests produce vector shift/add/sub instructions (`psllw`, `paddb`, `psubb`, etc.).
- [x] Step 2: Create `llvm/test/CodeGen/X86/vector-mul-i8-negative.ll` with edge case and non-decomposable tests.
- [x] Step 2a: Generate CHECK assertions for negative test cases.
- [x] Step 2b: Verify non-decomposable cases fall back to standard multiply or other optimizations.
- [x] Step 3: Add documentation comments to both test files explaining how to run and regenerate tests.
- [x] Step 4: Run all tests using `llvm-lit llvm/test/CodeGen/X86/vector-mul-i8-decompose.ll llvm/test/CodeGen/X86/vector-mul-i8-negative.ll`.
- [x] Step 4a: Fix any failing tests by adjusting IR test cases or investigating optimization bugs.
- [x] Step 4b: Run full X86 test suite to ensure no regressions: `llvm-lit llvm/test/CodeGen/X86/`.

**Note:** After each test file creation, compile LLVM and run the specific test to verify it passes before proceeding to the next step.

### Learnings from Implementation

#### Tool Setup and Usage
1. **Building llc**: The `llc` binary must be built before running `update_llc_test_checks.py`:
   ```powershell
   cd build
   cmake --build . --config Release --target llc
   ```
   The binary will be located at `build/Release/bin/llc.exe` on Windows.

2. **Auto-generating CHECK assertions**: Use absolute path to llc binary:
   ```powershell
   python llvm/utils/update_llc_test_checks.py --llc-binary "C:\Users\grodr\llvm-project\build\Release\bin\llc.exe" llvm/test/CodeGen/X86/mul-i8-decompose.ll
   ```
   Or run from project root without explicit path if llc is in PATH.

3. **Running individual tests with llvm-lit**: Use the build test directory and specify build_mode:
   ```powershell
   cd build/test
   python ../../llvm/utils/lit/lit.py --param=build_mode=Release -v CodeGen/X86/mul-i8-decompose.ll
   ```
   Or use the generated `llvm-lit.cmd` wrapper from build directory:
   ```powershell
   .\build\Release\bin\llvm-lit.cmd -v .\llvm\test\CodeGen\X86\mul-i8-decompose.ll
   ```

#### Test Implementation Insights
4. **Optimization scope**: This optimization targets vXi8 vector types only. Scalar i8 multiplies are already well-optimized by existing LLVM infrastructure using LEA (Load Effective Address) instructions for shift+add operations.

5. **Test file structure**: Tests should include:
   - Auto-generation comment at top
   - RUN line(s) specifying target triple and attributes
   - Documentation comments explaining the test purpose and how to run/regenerate
   - Test functions grouped by optimization category (powers of 2, sum, difference, negative, non-decomposable)
   - Use `nounwind` attribute on test functions to reduce assembly noise

6. **FileCheck patterns**: The `update_llc_test_checks.py` script generates precise CHECK patterns including:
   - `CHECK-LABEL:` for function names
   - `# %bb.0:` for basic block markers
   - Register kill/def comments (e.g., `# kill: def $al killed $al killed $eax`)
   - These patterns ensure assembly output matches exactly

7. **Verification approach**: After generating CHECK patterns, manually inspect a few functions to verify:
   - Power-of-2 multiplies use vector shifts (`psllw`/`vpsllw` with masking)
   - Sum decompositions use shift+add sequences (`psllw` + `paddb`)
   - Difference decompositions use shift+subtract (`psllw` + `psubb`)
   - Non-decomposable cases use appropriate fallback strategies

#### Vector Testing Considerations
8. **Vector instructions to expect**: For vXi8 types, look for:
   - `psllw`/`vpsllw` - vector shift left word (note: operates on 16-bit elements, needs masking for 8-bit)
   - `paddb`/`vpaddb` - vector byte addition
   - `psubb`/`vpsubb` - vector byte subtraction
   - `pand`/`vpand` - vector AND for masking after word-level shifts
   - May NOT see direct byte-level shifts since x86 lacks native `psllb` instruction

9. **Multiple RUN lines**: Different check-prefixes allow testing multiple architectures in one file:
   ```llvm
   ; RUN: llc < %s -mtriple=x86_64-unknown-unknown -mattr=+sse2 | FileCheck %s --check-prefixes=CHECK,SSE2
   ; RUN: llc < %s -mtriple=x86_64-unknown-unknown -mattr=+avx2 | FileCheck %s --check-prefixes=CHECK,AVX2
   ```
   Use `CHECK` prefix for common patterns and architecture-specific prefixes for differences.

### Further Considerations

1. **Architecture coverage**: Tests should cover SSE2 (baseline), AVX2 (v32i8), and AVX512BW (v64i8) to ensure the optimization works across different vector instruction sets.

2. **Constant selection strategy**: Which specific 8-bit constants should we test beyond the examples? Should we exhaustively test all decomposable constants, or a representative sample? Recommend representative sample (~20-30 constants) covering all decomposition patterns to keep test runtime reasonable.

### Test Coverage Issue and Resolution (November 2025)

#### Problem Identified
The original test suite in `vector-mul-i8-decompose.ll` was **not actually testing the new optimization**. All test constants (3, 5, 7, 9, 15, 17, 31, 33, 63, 65, 127, and their negatives) were of the form **2^n ± 1**, which were already being optimized by existing LLVM infrastructure before the decomposition optimization was implemented.

**Evidence**: When the decomposition optimization code was reverted and tests regenerated, the assembly output remained identical, confirming these constants were already optimized elsewhere (likely in DAGCombiner or target-specific lowering).

#### Root Cause
The **2^n ± 1** pattern is a special case already handled:
- **2^n - 1**: Optimized as `(a << n) - a` 
- **2^n + 1**: Optimized as `(a << n) + a`

This pattern only requires ONE shift plus one add/sub, making it attractive for existing optimizations.

#### Solution: New Test Constants
Tests were updated to use constants that are **sums or differences of two DIFFERENT powers of 2** (excluding the 2^n ± 1 pattern):

**Sum of two powers of 2:**
- **6** = 4 + 2 = 2^2 + 2^1
- **10** = 8 + 2 = 2^3 + 2^1
- **12** = 8 + 4 = 2^3 + 2^2
- **18** = 16 + 2 = 2^4 + 2^1
- **20** = 16 + 4 = 2^4 + 2^2
- **24** = 16 + 8 = 2^4 + 2^3
- **34** = 32 + 2 = 2^5 + 2^1
- **36** = 32 + 4 = 2^5 + 2^2
- **40** = 32 + 8 = 2^5 + 2^3
- **48** = 32 + 16 = 2^5 + 2^4

**Difference of two powers of 2 (excluding ±1):**
- **6** = 8 - 2 = 2^3 - 2^1
- **12** = 16 - 4 = 2^4 - 2^2
- **24** = 32 - 8 = 2^5 - 2^3
- **48** = 64 - 16 = 2^6 - 2^4
- **96** = 128 - 32 = 2^7 - 2^5

**Negative variants:**
- -6 (250), -10 (246), -12 (244), -24 (232)

#### Verification Process
After updating test constants:
1. Regenerated CHECK assertions with `update_llc_test_checks.py`
2. Verified current assembly (without optimization) uses `pmullw` (multiply word) instructions
3. Confirmed these are NOT shift-add-sub sequences, proving they're not pre-optimized
4. When decomposition optimization is re-applied, these should transform into efficient shift-add-sub sequences

#### Expected Decompositions
With the optimization enabled, these constants should produce:
- **6 = 4 + 2**: `(a << 2) + (a << 1)` → two shifts, one add
- **10 = 8 + 2**: `(a << 3) + (a << 1)` → two shifts, one add
- **12 = 8 + 4**: `(a << 3) + (a << 2)` → two shifts, one add
- **6 = 8 - 2**: `(a << 3) - (a << 1)` → two shifts, one subtract

#### x86 Vector Instruction Details
Note that x86 doesn't have byte-level shift instructions. The optimization uses:
- **`psllw`/`vpsllw`**: Packed Shift Left Logical Word (16-bit granularity)
- **`pand`/`vpand`**: Packed AND to mask overflow bits

Example for 2-bit shift on i8:
```asm
psllw $2, %xmm0          # Shift each 16-bit word left by 2
pand <0xFCFC...>, %xmm0  # Mask to keep only low byte bits
```

The mask prevents high bits of one byte from leaking into the next byte within each 16-bit word.

