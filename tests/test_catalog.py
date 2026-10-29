from pathlib import Path
import json
import re


def test_every_documented_voice_variant_is_in_the_local_catalog():
    root = Path(__file__).resolve().parents[1]
    catalog = json.loads((root / "ming_t8/assets/voices.json").read_text(encoding="utf-8"))["voices"]
    ids = {voice["id"] for voice in catalog}
    assert "灵小柔" in ids
    assert {voice["id"] for voice in catalog if voice["language"] == "English"} == {
        "US_Emma", "US_James", "US_Stella", "UK_George", "UK_Charlotte"}
    source = root / ".reference/Ming-3.0-tts/cookbooks/instructions.md"
    if source.is_file():
        table = source.read_text(encoding="utf-8").split('id="built-in-premium-voices"')[1].split('id="voice-design"')[0]
        variants = set(re.findall(r"`([^`]+)`", table))
        variants.discard("ip")  # Column header, not a voice identifier.
        assert variants <= ids, sorted(variants - ids)
