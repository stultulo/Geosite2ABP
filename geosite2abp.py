#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Usage:
    Usage: python geosite2abp.py [rule1] [rule2,rule3 ...] [-o <output_file>]
    Example: python geosite2abp.py gfw china-list -o my_rules.txt
"""

import sys
import re
from datetime import datetime
import urllib.request
from urllib.error import URLError
from typing import List, Set, Tuple

# Pre-compiled Regex
# Used in _convert_go_regex_to_js
RE_GO_ANCHOR_A = re.compile(r'(?<!\\)\\A')
RE_GO_ANCHOR_Z = re.compile(r'(?<!\\)\\[zZ]')
RE_JS_SLASH = re.compile(r'(?<!\\)/')

# Used in parse_inputs
RE_PARSE_INPUTS = re.compile(r"[,\s]+")


# Known rule sets from Loyalsoldier's repository
KNOWN = {
    "gfw",
    "china-list",
    "apple-cn",
    "google-cn",
    "win-spy",
    "win-update",
    "win-extra",
}

# Default output filename
DEFAULT_OUTFILE = "geosite2adb.txt"
# Total width for the block border lines
BLOCK_WIDTH = 48


def _make_border_line(it: str, kind: str) -> str:
    """
    Creates a border line with a total width of BLOCK_WIDTH.
    e.g., !-- gfw BEGIN --
    """
    core = f"{it} {kind}"
    # Ensure the core string isn't wider than the allowed block width
    core = core[:(BLOCK_WIDTH - 1)]
    
    return "!" + core.center(BLOCK_WIDTH - 1, '-') 


def _convert_go_regex_to_js(pattern: str) -> str:
    """
    Conservatively converts a Go/RE2-style regex pattern to a 
    JS-compatible one for ABP format.
    """
    # Replace anchors: \A -> ^, \z/\Z -> $
    pattern = RE_GO_ANCHOR_A.sub('^', pattern)
    pattern = RE_GO_ANCHOR_Z.sub('$', pattern)

    # Escape unescaped forward slashes for JS regex literals
    pattern = RE_JS_SLASH.sub(r'\/', pattern)
    
    return pattern


class GeositeProcessor:
    """
    Encapsulates the state and logic for processing a single root 
    rule item (e.g., 'gfw').
    
    Handles fetching, parsing, and converting geosite rules to ABP format.
    """
    
    # Pre-compiled Regex (Class Attributes)
    # Used in _process_line to find inline comments
    RE_INLINE_COMMENT = re.compile(r'[@#]')
    # Used in _process_line to clean domain rules
    RE_PROTOCOL = re.compile(r'^[\w\+\-\.]+://')
    RE_LEADING_WILDCARD = re.compile(r'^\*\.')

    def __init__(self, item: str):
        self.item = item
        self.visited: Set[str] = set()
        self.out_lines: List[str] = []
        self.rule_count: int = 0
        
        # Select the URL template based on the item name
        if item in KNOWN:
            self.template = "https://raw.githubusercontent.com/Loyalsoldier/v2ray-rules-dat/release/{it}.txt"
        else:
            self.template = "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data/{it}"
        
        self.root_url = self.template.format(it=item)

    def _fetch_url(self, url: str) -> str:
        """
        Fetches the content of a given URL.
        Prints an error and returns an empty string on failure.
        """
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except (URLError, TimeoutError) as e:
            print(f"[!] Failed to fetch {url}: {e}")
            return ""

    def _process_line(self, raw_line: str):
        """
        Processes a single line from a geosite file and adds
        the converted ABP-style rule(s) to self.out_lines.
        """
        
        # 1) Preserve empty lines
        s = raw_line.strip()
        if not s:
            self.out_lines.append("")
            return

        # 2) Handle full-line comments
        if s.startswith("#"):
            self.out_lines.append("!" + s[1:])
            return
        elif s.startswith("//"):
            self.out_lines.append("!" + s[2:])
            return
        elif s.startswith("!"):
            self.out_lines.append(s)
            return

        # 3) Remove inline comments
        s = self.RE_INLINE_COMMENT.split(s, 1)[0].rstrip()
        if not s:
            return

        low = s.lower()
        is_full = False 

        # 4) Handle directives (include, regexp, full)
        if low.startswith("include:"):
            inc = s.split(":", 1)[1].strip()
            if inc:
                self._fetch_and_process(inc)
            return
        
        elif low.startswith("regexp:"):
            pat = s.split(":", 1)[1].strip()
            if not pat:
                return
            js_pat = _convert_go_regex_to_js(pat)
            self.out_lines.append(f"/{js_pat}/")
            self.rule_count += 1
            return

        elif low.startswith("full:"):
            is_full = True
            s = s.split(":", 1)[1].strip()
            if not s:
                return
                
        # 5) Process domain rules
        s = self.RE_PROTOCOL.sub('', s).split('/')[0].split(':')[0]
        s = self.RE_LEADING_WILDCARD.sub('', s).lstrip('.')

        if not s:
            return

        # Generate the AdBlock Plus (ABP) format rule
        # | for exact domain, || for domain and subdomains
        rule = f"|{s}" if is_full else f"||{s}"
        self.out_lines.append(rule)
        self.rule_count += 1

    def _fetch_and_process(self, it: str):
        """
        Fetches and processes a rule item (e.g., 'gfw' or an 'include:').
        Uses self.visited to prevent recursion.
        """
        if it in self.visited:
            return
        self.visited.add(it)

        # Add a blank line for readability between included blocks
        if self.out_lines and self.out_lines[-1] != "":
            self.out_lines.append("")

        url = self.template.format(it=it)
        raw_content = self._fetch_url(url)
        if not raw_content:
            return

        for raw_line in raw_content.splitlines():
            self._process_line(raw_line)

    def process(self) -> Tuple[List[str], int]:
        """
        Executes the processor, returning the list of processed lines 
        and the total rule count.
        """
        self._fetch_and_process(self.item)
        return self.out_lines, self.rule_count


def parse_inputs(rule_args: List[str]) -> List[str]:
    """
    Parses a list of rule arguments into individual rule items.
    Handles mixed comma and space-separated inputs.
    e.g., ["gfw", "china-list,apple"] -> ["gfw", "china-list", "apple"]
    """
    raw = " ".join(rule_args)
    parts = [p.strip() for p in RE_PARSE_INPUTS.split(raw) if p.strip()]
    return parts


def main():
    # --- Argument Parsing ---
    output_file = DEFAULT_OUTFILE
    rule_args = []
    args = sys.argv[1:]
    i = 0

    while i < len(args):
        arg = args[i]
        if arg == '-o':
            # Check if there is a next argument
            if i + 1 < len(args):
                output_file = args[i+1]
                i += 2 # Skip both '-o' and the filename
            else:
                print("Error: -o flag requires a filename.", file=sys.stderr)
                sys.exit(1)
        else:
            rule_args.append(arg)
            i += 1
    
    # Now parse the collected rule arguments
    items = parse_inputs(rule_args)
    
    # Check if any rule items were provided
    if not items:
        print("Usage: python geosite2abp.py [rule1] [rule2,rule3 ...] [-o <output_file>]", file=sys.stderr)
        print("Example: python geosite2abp.py gfw china-list -o my_rules.txt", file=sys.stderr)
        sys.exit(1)
    # --- End of Argument Parsing ---

    items_str = ", ".join([f"geosite:{it}" for it in items])
    
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            # Write the file header
            timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
            f.write("[AutoProxy 0.2.9]\n")
            f.write(f"! The ruleset contains: {items_str}\n")
            f.write(f"! Last Modified: {timestamp}\n")
            f.write(f"! This list is generated by Geosite2ABP (https://github.com/stultulo/Geosite2ABP)\n")
            f.write(f"! It is based on data from:\n")
            f.write(f"! 1. v2fly/domain-list-community (MIT License)\n")
            f.write(f"! 2. Loyalsoldier/v2ray-rules-dat (GPL-3.0-or-later License)\n")
            f.write(f"\n")

            # Loop through and process each item
            for it in items:
                print(f"--- Processing: {it} ---")
                processor = GeositeProcessor(it)
                
                try:
                    lines, rule_count = processor.process()
                    url = processor.root_url

                    # Build the rule block
                    header_line = _make_border_line(it, "BEGIN")
                    footer_line = _make_border_line(it, "EOF")
                    
                    block_lines = [header_line, ""]
                    if lines:
                        block_lines.extend(lines)
                        block_lines.append("")
                    block_lines.append(footer_line)
                    
                    block = "\n".join(block_lines)
                    
                    f.write(block)
                    f.write("\n\n") 
                    
                    print(f"{it} -> {url} (Rules: {rule_count})")
                
                except Exception as e:
                    print(f"[!!!] An unexpected error occurred while processing {it}: {e}")
    
    except IOError as e:
        print(f"[!!!] Failed to write to file {output_file}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()