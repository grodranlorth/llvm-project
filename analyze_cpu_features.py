#!/usr/bin/env python3
"""
Analyze X86 CPU microarchitectures by GFNI and TuningFastImmVectorShift support.

Uses llvm-tblgen --dump-json to extract processor definitions and their features,
then buckets them by whether they support:
- FeatureGFNI (Galois Field Arithmetic Instructions)
- TuningFastImmVectorShift (Fast immediate vector shifts)
"""

import json
import subprocess
import sys
from pathlib import Path
from collections import defaultdict


def run_tblgen(llvm_root: Path) -> dict:
    """Run llvm-tblgen --dump-json on X86.td and return parsed JSON."""
    tblgen = llvm_root / "build" / "Release" / "bin" / "llvm-tblgen.exe"
    x86_td = llvm_root / "llvm" / "lib" / "Target" / "X86" / "X86.td"
    include_dirs = [
        llvm_root / "llvm" / "lib" / "Target" / "X86",
        llvm_root / "llvm" / "include",
    ]
    
    cmd = [str(tblgen)]
    for inc in include_dirs:
        cmd.extend(["-I", str(inc)])
    cmd.extend([str(x86_td), "--dump-json"])
    
    print(f"Running: {' '.join(cmd)}", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error running llvm-tblgen: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    
    return json.loads(result.stdout)


def get_all_superclasses(record: dict, all_records: dict) -> set:
    """Recursively get all superclass names for a record."""
    superclasses = set()
    for superclass_info in record.get("!superclasses", []):
        # superclass_info is [name, source_range]
        name = superclass_info[0] if isinstance(superclass_info, list) else superclass_info
        superclasses.add(name)
    return superclasses


def is_processor_model(record: dict) -> bool:
    """Check if a record is a ProcessorModel (CPU definition)."""
    superclasses = get_all_superclasses(record, {})
    return "ProcessorModel" in superclasses or "Processor" in superclasses


def resolve_list_ref(ref, all_records: dict) -> list:
    """Resolve a reference to a list in another record."""
    if isinstance(ref, dict) and "def" in ref:
        # It's a reference to a SubtargetFeature def
        return [ref["def"]]
    elif isinstance(ref, dict) and "kind" in ref:
        if ref["kind"] == "var":
            # Variable reference like ProcessorFeatures.SKLFeatures
            parts = ref.get("printable", "").split(".")
            if len(parts) == 2:
                class_name, var_name = parts
                # Look for the class definition
                if class_name in all_records:
                    class_record = all_records[class_name]
                    if var_name in class_record:
                        return resolve_feature_list(class_record[var_name], all_records)
        elif ref["kind"] == "def":
            return [ref["def"]]
    elif isinstance(ref, list):
        result = []
        for item in ref:
            result.extend(resolve_list_ref(item, all_records))
        return result
    return []


def resolve_feature_list(feature_data, all_records: dict) -> list:
    """Resolve a feature list, handling various TableGen representations."""
    features = []
    
    if isinstance(feature_data, list):
        for item in feature_data:
            if isinstance(item, dict):
                if "def" in item:
                    features.append(item["def"])
                elif "kind" in item:
                    features.extend(resolve_list_ref(item, all_records))
            elif isinstance(item, str):
                features.append(item)
    elif isinstance(feature_data, dict):
        if "def" in feature_data:
            features.append(feature_data["def"])
        elif "kind" in feature_data:
            features.extend(resolve_list_ref(feature_data, all_records))
    
    return features


def get_processor_features(proc_record: dict, all_records: dict) -> tuple:
    """
    Get the Features and TuneFeatures lists for a processor.
    Returns (feature_names, tune_feature_names)
    """
    features = []
    tune_features = []
    
    # ProcessorModel has Features and TuneFeatures fields
    if "Features" in proc_record:
        features = resolve_feature_list(proc_record["Features"], all_records)
    
    if "TuneFeatures" in proc_record:
        tune_features = resolve_feature_list(proc_record["TuneFeatures"], all_records)
    
    return features, tune_features


def expand_feature_deps(feature_name: str, all_records: dict, visited: set = None) -> set:
    """Recursively expand a feature to include all implied features."""
    if visited is None:
        visited = set()
    
    if feature_name in visited:
        return set()
    
    visited.add(feature_name)
    result = {feature_name}
    
    if feature_name in all_records:
        record = all_records[feature_name]
        # SubtargetFeature has "Implies" field
        if "Implies" in record:
            implies = resolve_feature_list(record["Implies"], all_records)
            for implied in implies:
                result.update(expand_feature_deps(implied, all_records, visited))
    
    return result


def main():
    llvm_root = Path(__file__).parent
    
    # Check for cached JSON file first
    json_cache = llvm_root / "x86-tblgen.json"
    if json_cache.exists():
        print(f"Using cached JSON from {json_cache}", file=sys.stderr)
        with open(json_cache, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = run_tblgen(llvm_root)
    
    all_records = data.get("!instanceof", {})
    
    # Get all ProcessorModel records
    processor_models = []
    for record_name, record_list in data.get("!instanceof", {}).items():
        if record_name in ["ProcessorModel", "Processor"]:
            processor_models.extend(record_list)
    
    # Also check for anonymous processor definitions
    for name, record in data.items():
        if name.startswith("!"):
            continue
        if isinstance(record, dict) and is_processor_model(record):
            if name not in processor_models:
                processor_models.append(name)
    
    # Collect all records into a flat dict for easier lookup
    records_dict = {}
    for name, record in data.items():
        if not name.startswith("!") and isinstance(record, dict):
            records_dict[name] = record
    
    # Buckets: (has_gfni, has_fast_imm_vector_shift) -> list of processor names
    buckets = defaultdict(list)
    
    print(f"\nFound {len(processor_models)} processor definitions", file=sys.stderr)
    
    for proc_name in processor_models:
        if proc_name not in records_dict:
            continue
        
        proc_record = records_dict[proc_name]
        
        # Get processor name (the Name field in ProcessorModel)
        cpu_name = proc_record.get("Name", proc_name)
        if isinstance(cpu_name, dict):
            cpu_name = cpu_name.get("value", proc_name)
        
        features, tune_features = get_processor_features(proc_record, records_dict)
        
        # Expand all features to include implied ones
        all_features = set()
        for feat in features:
            all_features.update(expand_feature_deps(feat, records_dict))
        
        all_tune_features = set(tune_features)
        
        # Check for GFNI and TuningFastImmVectorShift
        has_gfni = "FeatureGFNI" in all_features
        has_fast_imm_shift = "TuningFastImmVectorShift" in all_tune_features
        
        buckets[(has_gfni, has_fast_imm_shift)].append(cpu_name)
    
    # Print results
    print("\n" + "=" * 70)
    print("X86 Microarchitecture Feature Analysis")
    print("=" * 70)
    
    labels = {
        (False, False): "No GFNI, No FastImmVectorShift",
        (False, True): "No GFNI, Has FastImmVectorShift",
        (True, False): "Has GFNI, No FastImmVectorShift",
        (True, True): "Has GFNI, Has FastImmVectorShift",
    }
    
    for key in [(False, False), (False, True), (True, False), (True, True)]:
        cpus = sorted(set(buckets[key]))  # Remove duplicates and sort
        print(f"\n{labels[key]}: {len(cpus)} CPUs")
        print("-" * 50)
        for cpu in cpus:
            print(f"  {cpu}")
    
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    total = sum(len(set(v)) for v in buckets.values())
    for key in [(False, False), (False, True), (True, False), (True, True)]:
        count = len(set(buckets[key]))
        pct = count / total * 100 if total > 0 else 0
        print(f"  {labels[key]}: {count} ({pct:.1f}%)")
    print(f"\nTotal unique CPU definitions: {total}")


if __name__ == "__main__":
    main()
