"""
Phase 0 - throwaway script. Not part of the app.
Hits Tally's HTTP/XML server on localhost:9000 with a minimal request
and prints the raw response, so we can confirm:
  1. Tally responds at all
  2. Whether tags look like ERP 9 or TallyPrime conventions
Run with Tally open and "Enable ODBC Server" / HTTP-XML gateway on (F1 > Settings > Connectivity,
or Gateway of Tally > F12 > Advanced Configuration -> Client/Server configuration -> TCP/IP Port 9000).
"""
import urllib.request
import urllib.error

TALLY_URL = "http://localhost:9000"

MINIMAL_REQUEST = """<ENVELOPE>
 <HEADER>
  <VERSION>1</VERSION>
  <TALLYREQUEST>Export</TALLYREQUEST>
  <TYPE>Collection</TYPE>
  <ID>List of Companies</ID>
 </HEADER>
 <BODY>
  <DESC>
   <STATICVARIABLES>
    <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
   </STATICVARIABLES>
  </DESC>
 </BODY>
</ENVELOPE>"""


def main() -> None:
    print(f"POST {TALLY_URL} ...")
    data = MINIMAL_REQUEST.encode("utf-8")
    req = urllib.request.Request(TALLY_URL, data=data, headers={"Content-Type": "text/xml"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        print(f"FAILED to reach Tally at {TALLY_URL}: {e}")
        print("Checklist:")
        print("  - Is Tally open with a company loaded?")
        print("  - Gateway of Tally > F1 (Help) > Settings > Connectivity > Client/Server configuration")
        print("    -> TCP/IP port should be 9000 and 'Enable ODBC' / HTTP-XML server enabled")
        return

    print("--- RAW RESPONSE ---")
    print(raw)
    print("--- END RAW RESPONSE ---")

    lower = raw.lower()
    if "tallyprime" in lower:
        print("\nDetected hint: TallyPrime")
    elif "tally.erp" in lower or "erp 9" in lower:
        print("\nDetected hint: Tally.ERP 9")
    else:
        print("\nNo explicit version string found in this response.")
        print("Note the tag casing/structure above manually - it drives Phase 2 (tally_client.py).")
        print("TallyPrime and ERP 9 both generally use the same core export tags (VOUCHER, LEDGER, etc.)")
        print("but report-specific collection names/fields can differ - check Gateway of Tally > Help > About")
        print("for the exact version/release number and note it here.")


if __name__ == "__main__":
    main()
