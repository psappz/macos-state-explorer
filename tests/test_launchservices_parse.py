from macos_state_explorer.collectors.launchservices import parse_lsdump


def test_parse_orphaned():
    dump = '''
--------------------------------------------------------------------------------
bundle id:                  Chrome Helper (0xcd4)
Bundle node not found on disk: Error
path:                       /Applications/Google Chrome.app/Contents/Helpers/Google Chrome Helper.app (0x1c9c)
identifier:                 com.google.Chrome.helper
'''
    entries = parse_lsdump(dump, terms=["chrome"])
    assert entries
    assert entries[0]["classification"] in {"ORPHANED", "STALE"}
