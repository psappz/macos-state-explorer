# Local Network LaunchServices Repair Compatibility

`refresh-launchservices-user-cache` must not call `lsregister -kill`.

Recent macOS releases reject that option with:

```text
The -kill option has been removed because it was dangerous and no longer useful.
```

The Local Network repair action is limited to derived LaunchServices/user registration refresh behavior. It must not delete applications, Chrome profiles, TCC databases, user documents, or the LaunchServices database.

The supported refresh path is:

```text
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -r -f -apps user
```

Before executing the refresh, the action checks `lsregister -h` when possible and verifies that the required options (`-r`, `-f`, `-apps`) are advertised. If they are not available, the action fails clearly and directs the operator to the manual reinstall or trace fallback branch instead of retrying obsolete or destructive options.
