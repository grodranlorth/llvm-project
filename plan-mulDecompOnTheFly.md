## Plan: Remove MulDecompTable, Compute Decomposition On-The-Fly

Replace the global `MulDecompTable` / `getMulDecompTable()` with direct computation inside `X86TargetLowering::getMulByConstInfo(EVT, const APInt&) const`, and update `decomposeMulByConstant` to gate on the same predicate. This removes lazy global initialization (and its thread-safety concerns), keeps behavior identical for vXi8 constant splats, and colocates the “is decomposable?” decision with “how to decompose”.

### Contract to Preserve (Current Semantics)

**Scope / interpretation**
- Applies only to vector multiplies with scalar element size == i8 and the multiplier is a constant splat.
- The multiplier is interpreted as an 8-bit signed value (effectively `int8_t`, i.e. low 8 bits), and the decomposition is based on its absolute value `uc`.
- `Negate` means “negate the final result” (i.e. multiply by -1 after the shift/add/sub sequence), not bitwise inversion.

**When a constant is decomposable**
- `IsDecomposable == true` iff the absolute 8-bit value matches one of these patterns (with shifts in [0..7]):
  1) `uc = 2^x`
  2) `uc = 2^x + 2^y`
  3) `uc = 2^x - 2^y`
- Selection policy for the 2-shift forms must match current behavior:
  - Choose `2^y` as the lowest set bit of `uc`.
  - For sum: `uc - lowbit` must be a power of two.
  - For diff: `uc + lowbit` must be a power of two and must still fit in 8 bits (reject cases that would require shift >= 8, e.g. 255 via 256 - 1).

**Field invariants / meaning**
- `NumShifts` is in {0,1,2}:
  - 0: not decomposable
  - 1: use `Shift1` (and `Shift2 == 0`)
  - 2: use `Shift1` and `Shift2` combined by add/sub depending on `IsSub`
- For decomposable entries:
  - `Shift1` and `Shift2` are shift amounts in [0..7]
  - for the two-shift form, `Shift1 > Shift2`
  - `IsSub` selects `shl(Shift1) - shl(Shift2)` vs `+`
- Explicit edge cases to preserve:
  - `uc == 0` and `uc == 1` remain not decomposable.
  - Handling of `-128` (abs is 128) remains consistent with existing behavior.

### Steps

1) Introduce a single per-constant decomposition helper
- Add a small helper (e.g. `computeMulByConstInfoI8(uint8_t)` or `computeMulByConstInfoI8Signed(int8_t)`) that returns a `MulByConstInfo` for exactly one i8 constant, following the contract above.
- This is the “right place” to centralize the logic so both gating and lowering can call it.

2) Use the helper from `X86TargetLowering::getMulByConstInfo`
- Replace the table lookup with direct computation using the same lowbit-based algorithm.
- Use LLVM helpers (`isPowerOf2_*`, `llvm::countr_zero`) rather than ad-hoc bit tests.
- Keep the behavior limited to vXi8 splat constants.

3) Update `X86TargetLowering::decomposeMulByConstant` gating
- Replace the `getMulDecompTable()[uc].IsDecomposable` check with the same predicate used by the new on-the-fly code.
- Ensure this stays in sync with `getMulByConstInfo` so DAGCombiner continues to query the target hook in the same cases.

4) Remove the table
- Delete `MulDecompTable` and `getMulDecompTable()` and any now-unused helpers.

5) Validate
- Run:
  - `build/bin/llvm-lit -v llvm/test/CodeGen/X86/vector-mul-i8-decompose.ll`
  - `build/bin/llvm-lit -v llvm/test/CodeGen/X86/vector-mul-i8-negative.ll`
- If there is any behavior drift, adjust the on-the-fly logic to re-match the contract.

### Notes / Pitfalls
- `decomposeMulByConstant` must stay consistent with `getMulByConstInfo` or the optimization may silently stop triggering.
- Removing the lazy global initialization avoids concurrency hazards from non-atomic initialization guards.
