import argparse
import json
import os
import sys
from pathlib import Path

from .audit import inspect_sources
from .config import TestConfig
from .probes import run_probes


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Prerequisites for a future Frappe/ERPNext OriginChainDB backend"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    audit = sub.add_parser("audit", help="Inspect pinned upstream checkouts without executing them")
    audit.add_argument("--frappe", type=Path, required=True)
    audit.add_argument("--erpnext", type=Path, required=True)
    audit.add_argument("--output", type=Path, required=True)
    live = sub.add_parser("probe", help="Run eight prerequisites against an explicit disposable SQL database")
    live.add_argument("--allow-scratch-writes", action="store_true")
    live.add_argument("--reference-postgres", action="store_true")
    live.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "audit":
            report = inspect_sources({"frappe": args.frappe, "erpnext": args.erpnext})
            passed = report["audit_complete"]
        else:
            if not args.allow_scratch_writes:
                raise ValueError("Use --allow-scratch-writes only with a disposable database")
            config = TestConfig.from_environment(os.environ, reference_postgres=args.reference_postgres)
            report = run_probes(config, allow_scratch_writes=True)
            passed = report["all_prerequisites_passed"]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 3
    except ImportError:
        print('Install the live extra: pip install ".[live]"', file=sys.stderr)
        return 3
    except Exception as error:
        # Avoid printing driver messages, DSNs, connection details or environment values.
        print(
            f"Operation failed ({type(error).__name__}); no compatibility verdict produced.", file=sys.stderr
        )
        return 3
    print(f"{'PASS' if passed else 'FAIL'}: {args.command}. Frappe/ERPNext compatibility remains unverified.")
    return 0 if passed else 2
