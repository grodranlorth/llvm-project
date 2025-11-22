# LLVM Project Copilot Instructions

## General Guidelines
- When following a plan file and encountering a critical issue not accounted for in the plan (e.g., toolchain incompatibility, missing dependencies, architectural problems), STOP and ask the user how to proceed before attempting workarounds.

- Save planning documents: Write any new or updated planning documents to the `planning/` directory at the repository root. Create the directory if it does not exist.

## Build Instructions
- Build `llc`: `cd build; cmake --build . --config Release --target llc -j32`
- Full build: `cd build; cmake --build . --config Release -j32`

## Running Tests
- Individual test: `.\build\Release\bin\llvm-lit.cmd -v .\llvm\test\CodeGen\X86\<test-file>.ll`
- All X86 tests: `.\build\Release\bin\llvm-lit.cmd -v .\llvm\test\CodeGen\X86\`
- From test dir: `cd build/test; python ../../llvm/utils/lit/lit.py --param=build_mode=Release -v CodeGen/X86/<test-file>.ll`

## Running llc
- Direct assembly: `.\build\Release\bin\llc.exe -mtriple=x86_64-unknown-unknown -mattr=+sse2 .\llvm\test\CodeGen\X86\<test-file>.ll -o -`
- With AVX2: `-mattr=+avx2`
- With AVX512: `-mattr=+avx512bw`

## Regenerating CHECK Assertions
- `python llvm\utils\update_llc_test_checks.py --llc-binary "build\Release\bin\llc.exe" llvm\test\CodeGen\X86\<test-file>.ll`

## 8-Bit Vector Multiply Optimization Context
- Goal: for generic targets (e.g. baseline `x86-64-v1`, i.e. not gated on tuning features), lower vXi8 splat multiplies by suitable constants into short shift+add/sub sequences
- Note: a similar shift+add/sub optimization already exists in LLVM, but is gated behind tuning (e.g. `TuningFastImmVectorShift`) and is therefore not enabled for generic targets
- Must eliminate the widen+pack/unpack lowering pattern (e.g. `splat => mul16 => and => packuswb` / `vpmovzxbw => vpmullw => vpand => vpackuswb`), not just replace the `pmullw`
- Targets vXi8 vector types only (v16i8, v32i8, v64i8); scalar i8 uses LEA
- Test constants: sums/differences of two different powers of 2 (e.g., 6=4+2, 10=8+2, 12=8+4, 24=16+8, 6=8-2, 12=16-4)
- Avoid 2^n ±1 patterns (3,5,7,9,15,17,31,33,63,65,127) as they're pre-optimized
- Expected output: `psllw`/`vpsllw` + `pand`/`vpand` for shifts, `paddb`/`vpaddb`/`psubb`/`vpsubb` for add/sub
- Test files: `llvm/test/CodeGen/X86/vector-mul-i8-decompose.ll` (positive), `llvm/test/CodeGen/X86/vector-mul-i8-negative.ll` (negative)
