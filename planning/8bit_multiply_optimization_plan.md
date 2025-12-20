## Plan: Integrate 8-Bit Multiply Constant Decomposition Optimization

Lazily compute a table for all 256 8-bit constants, storing decomposition state (invert, nshifts, shift1, shift2, sub) for those writable as sum of two powers of 2. Integrate into X86ISelLowering.cpp to detect decomposable constants and DAGCombiner.cpp to emit optimized DAG nodes (shifts, adds, subs, negates) instead of multiplies, improving performance for vXi8 multiplies.

### Steps
1. Define `MulDecompEntry` struct in `llvm/lib/Target/X86/X86ISelLowering.cpp`. Add a static array `MulDecompTable[256]` initialized to indicate uncomputed entries. Implement a lazy computation function that computes the entry for a given 8-bit constant m on first access:
   - No changes needed to `X86TargetLowering` or `TargetLowering` interfaces; modify existing overridden `decomposeMulByConstant`.
   - For computing `MulDecompEntry` for m:
     - If m == 0 or m == 1, set nshifts = 0 (not decomposable).
     - If m is negative (for signed interpretation), set invert = true and work with abs(m).
     - Try to find if m = 2^x + 2^y where x > y >= 0: Iterate possible y from 0 to 7, check if (m - 2^y) is power of 2, set shift1 = x, shift2 = y, sub = false, nshifts = 2.
     - If not found, try m = 2^x - 2^y: Iterate y, check if (m + 2^y) is power of 2, set shift1 = x, shift2 = y, sub = true, nshifts = 2.
     - If still not, check if m is power of 2: set nshifts = 1, shift1 = log2(m), shift2 = 0, sub = false.
     - Otherwise, set nshifts = 0.
     - Prioritize simplicity: Prefer nshifts=1 over 2, and smaller shifts.
2. Modify `decomposeMulByConstant` in `llvm/lib/Target/X86/X86ISelLowering.cpp` to return true for vXi8 vectors if `MulDecompTable[C.getZExtValue()].nshifts > 0`.
3. Update `visitMUL` in `llvm/lib/CodeGen/SelectionDAG/DAGCombiner.cpp` to emit custom DAG nodes for vXi8 cases: After the existing generic decomposition logic, add a check `if (VT.getScalarSizeInBits() == 8 && VT.isVector() && MulC.getBitWidth() == 8)`. Access the table entry via a call to X86TargetLowering's helper method. Based on the entry:
   - If nshifts == 1: Emit `SHL` of N0 by shift1.
   - If nshifts == 2: Emit `SHL` of N0 by shift1, `SHL` of N0 by shift2, then `ADD` or `SUB` based on `sub`.
   - If invert: Wrap the result in `NEG`.
   - Ensure vector operations are handled correctly for splat constants.
4. Add a private helper method in `X86TargetLowering` class to retrieve and apply table-based decomposition, ensuring type legality and overflow handling.

### Implementation Checklist
- [x] Step 1: Define `MulDecompEntry` struct and implement lazy table computation in `X86ISelLowering.cpp`.
- [x] Step 2: Modify `decomposeMulByConstant` to check the table for vXi8 vectors.
- [x] Step 3: Update `visitMUL` in `DAGCombiner.cpp` to emit DAG nodes based on table entries for vXi8.
- [x] Step 4: Add private helper method in `X86TargetLowering` for table access and decomposition.

**Note:** Verify compilation after each step by building the LLVMX86CodeGen target from the build/ directory (e.g., `cd build && cmake --build . --config Release --target LLVMX86CodeGen`).

### Further Considerations
1. Edge cases: Constants like 0, 1, or non-decomposable (e.g., 17) are handled by setting nshifts=0, ensuring fallback to standard multiply.
2. Integration scope: This is X86-specific, placed in X86ISelLowering.cpp; no need for generic DAGCombiner extension for other backends.