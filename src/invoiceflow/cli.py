"""python -m invoiceflow.cli run <folder> --out out --preset xero [--llm] [--approve-vendor NAME [--bank IBAN]]"""
import argparse
import os
import sys
from pathlib import Path

from .audit import AuditLog
from .config import load_config
from .export import PRESETS, write_outputs
from .extractors import ClaudeVisionExtractor, FallbackExtractor, GPTVisionExtractor, TextLayerExtractor
from .ledger import Ledger
from .pipeline import Pipeline
from .validate import VendorMemory


def main(argv=None):
    ap = argparse.ArgumentParser(prog="invoiceflow")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="process a folder of invoices")
    run.add_argument("folder")
    run.add_argument("--out", default="out")
    run.add_argument("--preset", choices=sorted(PRESETS), default="generic")
    run.add_argument("--config", default=None)
    run.add_argument("--llm", nargs="?", const="claude", choices=["claude", "gpt"],
                     help="read with a vision model: claude (ANTHROPIC_API_KEY) or gpt (OPENAI_API_KEY); costs money. Omit for the free rule-based reader")
    ven = sub.add_parser("approve-vendor", help="mark a vendor as known after a human has checked it")
    ven.add_argument("name")
    ven.add_argument("--bank", default=None)
    ven.add_argument("--out", default="out")
    args = ap.parse_args(argv)
    out = Path(args.out)
    memory = VendorMemory(out / "vendors.json")
    if args.cmd == "approve-vendor":
        memory.remember(args.name, args.bank.replace(" ", "").upper() if args.bank else None)
        print(f"vendor remembered: {args.name}")
        return 0
    extractor = TextLayerExtractor()
    if args.llm == "gpt":
        import openai
        if not os.environ.get("OPENAI_API_KEY"):
            print("OPENAI_API_KEY is not set", file=sys.stderr)
            return 2
        extractor = FallbackExtractor(GPTVisionExtractor(openai.OpenAI()), TextLayerExtractor())
    elif args.llm:
        import anthropic
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("ANTHROPIC_API_KEY is not set", file=sys.stderr)
            return 2
        extractor = FallbackExtractor(ClaudeVisionExtractor(anthropic.Anthropic()), TextLayerExtractor())
    pipe = Pipeline(extractor, load_config(args.config), Ledger(out / "ledger.jsonl"), memory, AuditLog(out / "audit.jsonl"))
    decisions = pipe.process_folder(args.folder)
    counts = write_outputs(decisions, out, args.preset)
    print(counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
