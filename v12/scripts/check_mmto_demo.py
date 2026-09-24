"""Check a fresh MMTO example solution against its release baseline."""
import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def check_result(result: dict, baseline: dict) -> list[str]:
    limits = baseline["acceptance"]
    fit = result["fit"]
    camera = result["camera"]
    image = result["input_image"]
    exposure = image["exposure"]
    checks = {
        "approved MMTO input checksum":
            result["source_sha256"] == baseline["source_sha256"],
        "frozen catalogue checksum":
            result["catalogue_sha256"] == baseline["catalogue_sha256"],
        "converged fit": result["status"] == "point_star_fit_converged",
        "blind stellar fit":
            result["metadata_used"] is False and result["trails_used"] is False,
        "no withheld stars": result["withheld_stars"] == 0,
        "detection count": result["detection_count"] >= limits["minimum_detections"],
        "association count": fit["count"] >= limits["minimum_associated_stars"],
        "RMS residual": 0 <= fit["rms_px"] <= limits["maximum_rms_px"],
        "median residual": 0 <= fit["median_px"] <= limits["maximum_median_px"],
        "90th percentile residual": 0 <= fit["p90_px"] <= limits["maximum_p90_px"],
        "angular RMS residual":
            0 <= fit["rms_arcmin"] <= limits["maximum_rms_arcmin"],
        "large/saturated objects retained":
            result["broad_or_saturated_objects"]
            >= limits["minimum_broad_or_saturated_objects"],
        "native RGB planes":
            image["format"] == "fits" and image["plane_names"] == ["R", "G", "B"],
        "native depth preserved": image["native_depth_preserved"] is True,
        "compressed FITS input": image["source_compression"] == "bz2",
        "recorded exposure":
            exposure["status"] == "available"
            and exposure["seconds"] == limits["exposure_seconds"],
        "MMTO detector shape": camera["shape"] == [1411, 1422],
        "MMTO detector parity": camera["detector_parity"] == "mirrored",
        "monotonic radial model": camera["monotonic_on_detector"] is True,
    }
    return [name for name, passed in checks.items() if not passed]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = json.loads((args.output/"result.json").read_text())
    baseline = json.loads((ROOT/"examples/mmto/baseline.json").read_text())
    failures = check_result(result, baseline)
    if failures:
        raise SystemExit("Baseline FAILED: " + ", ".join(failures))
    fit = result["fit"]
    print(
        f"Baseline PASS: {fit['count']} associations, "
        f"RMS {fit['rms_px']:.6f} px ({fit['rms_arcmin']:.3f} arcmin)"
    )


if __name__ == "__main__":
    main()
