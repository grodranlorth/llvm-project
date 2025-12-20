# Test Coverage Issue: 8-Bit Vector Multiply Optimization

## Summary

The test suite for the 8-bit vector multiply constant decomposition optimization (`vector-mul-i8-decompose.ll`) is **not actually testing the new optimization**. All current test constants are already optimized by existing LLVM infrastructure.

## The Problem

All test constants in `vector-mul-i8-decompose.ll` are of the form **2^n ± 1**, which were already being optimized before our new decomposition optimization was implemented:

### Current Test Constants (Already Optimized)
- **3** = 2^2 - 1 (4 - 1)
- **5** = 2^2 + 1 (4 + 1)
- **7** = 2^3 - 1 (8 - 1)
- **9** = 2^3 + 1 (8 + 1)
- **15** = 2^4 - 1 (16 - 1)
- **17** = 2^4 + 1 (16 + 1)
- **31** = 2^5 - 1 (32 - 1)
- **33** = 2^5 + 1 (32 + 1)
- **63** = 2^6 - 1 (64 - 1)
- **65** = 2^6 + 1 (64 + 1)
- **127** = 2^7 - 1 (128 - 1)
- **-3, -5, -7** = negatives of the above
- **-128** = -2^7 (power of 2)

### Evidence

When the decomposition optimization code is reverted and the test file is rebuilt:
1. The `llc` binary is successfully rebuilt
2. Running `llc` directly on the test file produces identical assembly
3. Regenerating CHECK assertions with `update_llc_test_checks.py` produces no changes

This confirms that the existing LLVM optimization passes (likely in DAGCombiner or target-specific lowering) already handle `2^n ± 1` constants efficiently.

## What Should Be Tested

To actually verify the new decomposition optimization, we need constants that are **sums or differences of two DIFFERENT powers of 2** (excluding the `2^n ± 1` pattern):

### Recommended Test Constants

**Sum of two powers of 2:**
- **6** = 2^2 + 2^1 = 4 + 2
- **10** = 2^3 + 2^1 = 8 + 2
- **12** = 2^3 + 2^2 = 8 + 4
- **18** = 2^4 + 2^1 = 16 + 2
- **20** = 2^4 + 2^2 = 16 + 4
- **24** = 2^4 + 2^3 = 16 + 8
- **34** = 2^5 + 2^1 = 32 + 2
- **36** = 2^5 + 2^2 = 32 + 4
- **40** = 2^5 + 2^3 = 32 + 8
- **48** = 2^5 + 2^4 = 32 + 16

**Difference of two powers of 2 (excluding ±1):**
- **6** = 2^3 - 2^1 = 8 - 2
- **12** = 2^4 - 2^2 = 16 - 4
- **24** = 2^5 - 2^3 = 32 - 8
- **48** = 2^6 - 2^4 = 64 - 16
- **96** = 2^7 - 2^5 = 128 - 32

**Negative variants:**
- **-6, -10, -12, -18, -20, -24, etc.**

## Task

1. **Add test cases** for constants that are sums/differences of two different powers of 2
2. **Verify** these tests fail (use non-optimized multiply) when the decomposition optimization is reverted
3. **Verify** these tests pass (use optimized shift-add-sub sequences) with the optimization enabled
4. **Update** the plan document to reflect this coverage improvement

## Expected Decompositions

Examples of what the optimization should produce:

- **6 = 4 + 2**: `(a << 2) + (a << 1)` → shift by 2, shift by 1, add
- **10 = 8 + 2**: `(a << 3) + (a << 1)` → shift by 3, shift by 1, add
- **12 = 8 + 4**: `(a << 3) + (a << 2)` → shift by 3, shift by 2, add
- **6 = 8 - 2**: `(a << 3) - (a << 1)` → shift by 3, shift by 1, subtract

## Notes on x86 Vector Instructions

### The Masking Pattern (`pand`)

When examining assembly output, note that x86 doesn't have byte-level shift instructions. The optimization uses:
- **`psllw`**: Packed Shift Left Logical **Word** (16-bit granularity)
- **`pand`**: Packed AND to mask bits that overflow into neighboring bytes

Example for a 2-bit shift on i8 values:
```asm
psllw $2, %xmm0          # Shift each 16-bit word left by 2
pand <0xFCFC...>, %xmm0  # Mask to keep only low byte bits
```

The mask prevents high bits of one byte from leaking into the next byte within each 16-bit word.

## File Locations

- **Positive tests**: `llvm/test/CodeGen/X86/vector-mul-i8-decompose.ll`
- **Negative tests**: `llvm/test/CodeGen/X86/vector-mul-i8-negative.ll`
- **Plan document**: `plan-8bitMultiplyOptimizationUnitTests.prompt.md`
- **Optimization code**: Likely in `llvm/lib/CodeGen/SelectionDAG/DAGCombiner.cpp` or target-specific files

## Build Commands

```powershell
# Rebuild llc after code changes
cd build
cmake --build . --config Release --target llc

# Run tests
.\build\Release\bin\llvm-lit.cmd -v .\llvm\test\CodeGen\X86\vector-mul-i8-decompose.ll

# Regenerate CHECK assertions
python llvm\utils\update_llc_test_checks.py --llc-binary "build\Release\bin\llc.exe" llvm\test\CodeGen\X86\vector-mul-i8-decompose.ll

# Test llc directly to verify assembly output
.\build\Release\bin\llc.exe -mtriple=x86_64-unknown-unknown -mattr=+sse2 .\llvm\test\CodeGen\X86\vector-mul-i8-decompose.ll -o -
```
