# Plan: Verify vXi8 Multiply Table Computation Follows LLVM Patterns

## Objective
Verify that the lazy table computation for the vXi8 multiply optimization (commit aaa3e69974351155cb6588b56034c94e16fd2e14) uses the same approach as similar table-based optimizations in LLVM.

## Current Implementation Analysis

### vXi8 Multiply Table (`llvm/lib/Target/X86/X86ISelLowering.cpp`)

**Location:** Lines 80-151

**Pattern:**
```cpp
static TargetLowering::MulByConstInfo MulDecompTable[256];

const TargetLowering::MulByConstInfo* getMulDecompTable() {
  static bool Initialized = false;
  if (!Initialized) {
    for (int i = 0; i < 256; i++) {
      // ... compute table entries ...
    }
    Initialized = true;
  }
  return MulDecompTable;
}
```

**Characteristics:**
- **Static array**: File-scope static array `MulDecompTable[256]`
- **Function-scope static flag**: `static bool Initialized = false` inside function
- **Thread safety**: ❌ **NOT thread-safe** - uses plain `bool`, not `std::atomic<bool>`
- **Verification**: ❌ No assertions or validation of table contents
- **Initialization**: Lazy - computed on first call to `getMulDecompTable()`
- **Scope**: File-scope array, function-scope flag

## LLVM Table Pattern Survey

### Pattern A: Static Const Tables with Atomic Verification (Debug Only)

**Example 1: X86InstrFoldTables.cpp (lines 90-115)**
```cpp
static const X86FoldTableEntry *
lookupFoldTableImpl(ArrayRef<X86FoldTableEntry> Table, unsigned RegOp) {
#ifndef NDEBUG
  static std::atomic<bool> FoldTablesChecked(false);
  if (!FoldTablesChecked.load(std::memory_order_relaxed)) {
    CHECK_SORTED_UNIQUE(Table2Addr)
    // ... more checks ...
    FoldTablesChecked.store(true, std::memory_order_relaxed);
  }
#endif
  // ... lookup logic ...
}
```

**Characteristics:**
- **Static const tables**: Compile-time initialized data
- **Atomic verification**: `std::atomic<bool>` with `memory_order_relaxed`
- **Debug-only**: Verification wrapped in `#ifndef NDEBUG`
- **Thread-safe**: Atomic operations ensure thread safety

**Example 2: X86FloatingPoint.cpp (lines 620-630)**
```cpp
#ifdef NDEBUG
#define ASSERT_SORTED(TABLE)
#else
#define ASSERT_SORTED(TABLE)                                                   \
  {                                                                            \
    static std::atomic<bool> TABLE##Checked(false);                            \
    if (!TABLE##Checked.load(std::memory_order_relaxed)) {                     \
      assert(is_sorted(TABLE) &&                                               \
             "All lookup tables must be sorted for efficient access!");        \
      TABLE##Checked.store(true, std::memory_order_relaxed);                   \
    }                                                                          \
  }
#endif
```

**Characteristics:**
- **Macro pattern**: Reusable verification macro
- **Per-table atomic**: Token pasting creates unique atomic flag per table
- **Memory order relaxed**: Sufficient for one-time checks
- **Release builds**: Zero overhead - macro expands to nothing

### Pattern B: Function-Scope Static with Constructor Initialization

**Example: X86InstrFoldTables.cpp (lines 166-233)**
```cpp
namespace {
struct X86MemUnfoldTable {
  std::vector<X86FoldTableEntry> Table;

  X86MemUnfoldTable() {
    // ... compute table from other tables ...
    array_pod_sort(Table.begin(), Table.end());
    assert(std::adjacent_find(Table.begin(), Table.end()) == Table.end() &&
           "Memory unfolding table is not unique!");
  }
};
} // namespace

const X86FoldTableEntry *llvm::lookupUnfoldTable(unsigned MemOp) {
  static X86MemUnfoldTable MemUnfoldTable;  // C++11 thread-safe init
  auto &Table = MemUnfoldTable.Table;
  // ... lookup ...
}
```

**Characteristics:**
- **Function-scope static**: Initialized once on first call
- **Constructor initialization**: Computation in constructor
- **Thread-safe**: C++11+ guarantees thread-safe static local initialization
- **Validation**: Assertions in constructor
- **No explicit flag needed**: Language guarantees handle initialization

### Pattern C: Plain Static Flag (Less Common)

**Found in:** Only in our vXi8 implementation!

**Thread Safety Issue:**
The current implementation uses `static bool Initialized = false` without atomic operations. This has potential race conditions:
1. Thread A checks `if (!Initialized)` → true
2. Thread B checks `if (!Initialized)` → true (before A sets it)
3. Both threads initialize the table simultaneously
4. Non-deterministic behavior

## Comparison Matrix

| Feature | vXi8 (Current) | X86InstrFoldTables | X86FloatingPoint | X86MemUnfoldTable |
|---------|---------------|-------------------|------------------|-------------------|
| **Table Storage** | File-scope static array | File-scope static const | File-scope static const | Function-scope static struct |
| **Initialization** | Lazy (function-scope flag) | Compile-time | Compile-time | Lazy (C++ static local) |
| **Thread Safety** | ❌ Plain `bool` | ✅ `std::atomic<bool>` | ✅ `std::atomic<bool>` | ✅ C++11 static local guarantee |
| **Verification** | ❌ None | ✅ Debug-only asserts | ✅ Debug-only macro | ✅ Constructor asserts |
| **Memory Order** | N/A | `relaxed` | `relaxed` | N/A (language guarantee) |
| **When Used** | Computed tables | Static const verification | Static const verification | Computed from static tables |

## Issues Identified

### 🔴 **CRITICAL: Thread Safety**
The current implementation is **NOT thread-safe**. It uses a plain `bool` flag without atomic operations, which can lead to:
- Data races on the `Initialized` flag
- Multiple concurrent initializations of `MulDecompTable`
- Undefined behavior in multi-threaded compilation

### 🟡 **MINOR: No Validation**
Unlike other LLVM tables, there's no validation that the computed table is correct:
- No assertions checking table properties
- No verification in debug builds
- Silent failures if computation is incorrect

### 🟡 **STYLE: Inconsistent Pattern**
The implementation doesn't match any of the three common LLVM patterns:
- Not Pattern A (static const with atomic verification)
- Not Pattern B (function-scope static with C++11 guarantees)
- Uses a unique pattern not found elsewhere in X86 backend

## Recommended Fix

### Option 1: Use Atomic Flag (Minimal Change)
```cpp
const TargetLowering::MulByConstInfo* getMulDecompTable() {
  static std::atomic<bool> Initialized(false);
  if (!Initialized.load(std::memory_order_relaxed)) {
    for (int i = 0; i < 256; i++) {
      // ... compute table entries ...
    }
    Initialized.store(true, std::memory_order_relaxed);
  }
  return MulDecompTable;
}
```

**Pros:** Minimal change, thread-safe, matches LLVM patterns
**Cons:** Still has theoretical race window (table might be read while being written)

### Option 2: Function-Scope Static Struct (Best Practice)
```cpp
namespace {
struct MulDecompTableHolder {
  TargetLowering::MulByConstInfo Table[256];
  
  MulDecompTableHolder() {
    for (int i = 0; i < 256; i++) {
      int8_t c = (int8_t)i;
      // ... initialization logic ...
      
      // Add validation
      assert((!Table[i].IsDecomposable || Table[i].NumShifts > 0) &&
             "Decomposable entry must have shifts");
    }
  }
};
} // namespace

const TargetLowering::MulByConstInfo* getMulDecompTable() {
  static MulDecompTableHolder Holder;  // C++11 guarantees thread-safe init
  return Holder.Table;
}
```

**Pros:** 
- Fully thread-safe (C++11 language guarantee)
- Matches LLVM Pattern B (X86MemUnfoldTable)
- Can add validation in constructor
- No race conditions possible

**Cons:** More code restructuring required

### Option 3: llvm::call_once (Explicit Control)
```cpp
static llvm::once_flag InitFlag;
static TargetLowering::MulByConstInfo MulDecompTable[256];

static void initializeMulDecompTable() {
  for (int i = 0; i < 256; i++) {
    // ... initialization ...
  }
}

const TargetLowering::MulByConstInfo* getMulDecompTable() {
  llvm::call_once(InitFlag, initializeMulDecompTable);
  return MulDecompTable;
}
```

**Pros:** Explicit, clear intent, thread-safe
**Cons:** More verbose, less common in X86 backend

## Recommendation

**Implement Option 2: Function-Scope Static Struct**

This approach:
1. ✅ Matches established LLVM patterns (X86MemUnfoldTable)
2. ✅ Provides guaranteed thread safety via C++11 static local initialization
3. ✅ Allows adding validation assertions
4. ✅ No explicit synchronization needed
5. ✅ Clean separation of concerns (initialization in constructor)

## Action Items

- [ ] Refactor `getMulDecompTable()` to use function-scope static struct pattern
- [ ] Add validation assertions in constructor (debug builds)
- [ ] Document the pattern choice in code comments (referencing X86MemUnfoldTable as precedent)

## References

- **Pattern A Examples:**
  - `llvm/lib/Target/X86/X86InstrFoldTables.cpp:90-115`
  - `llvm/lib/Target/X86/X86FloatingPoint.cpp:620-630`
  - `llvm/lib/Target/X86/X86InstrFMA3Info.cpp:143`
  
- **Pattern B Examples:**
  - `llvm/lib/Target/X86/X86InstrFoldTables.cpp:166-233` (X86MemUnfoldTable)
  - `llvm/lib/Target/X86/X86InstrFoldTables.cpp:242+` (X86BroadcastFoldTable)

- **C++11 Static Local Guarantee:**
  - C++11 Standard §6.7 [stmt.dcl]/4: "If control enters the declaration concurrently while the variable is being initialized, the concurrent execution shall wait for completion of the initialization."
