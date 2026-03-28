"""
scripts/shared/html_utils.py
Helper to inject data objects into HTML dashboard templates.

Templates contain a placeholder comment:
    <!-- DATA_INJECTION_POINT -->

This is replaced with a <script> block containing const declarations for
whichever data objects are passed in (GA4, AMP, HS).
"""

import json
import os
import re


PLACEHOLDER = "<!-- DATA_INJECTION_POINT -->"


def inject_data(template_path: str, data_dict: dict, output_path: str):
    """
    Inject one or more data objects into an HTML template file.

    Args:
        template_path: Path to the HTML template (contains <!-- DATA_INJECTION_POINT -->)
        data_dict: Dict mapping JS variable names to Python dicts/objects.
                   Example: {"GA4": ga4_payload, "AMP": amp_payload}
        output_path: Where to write the resulting HTML file.

    The placeholder comment is replaced with:
        <script>
        const GA4 = {...};
        const AMP = {...};
        </script>
    """
    # Read template
    with open(template_path, encoding="utf-8") as f:
        html = f.read()

    if PLACEHOLDER not in html:
        raise ValueError(
            f"Placeholder '{PLACEHOLDER}' not found in template: {template_path}"
        )

    # Build script block
    lines = ["<script>"]
    for var_name, data in data_dict.items():
        json_str = json.dumps(data, separators=(",", ":"))
        lines.append(f"const {var_name} = {json_str};")
    lines.append("</script>")
    script_block = "\n".join(lines)

    # Replace placeholder
    html = html.replace(PLACEHOLDER, script_block, 1)

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Write output
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    kb = len(html.encode("utf-8")) / 1024
    print(f"✅  Written {output_path} ({kb:.1f} KB)")
