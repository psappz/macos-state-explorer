# Local Network case study

Observed model:

```text
System Settings
  -> privacy daemon/cache layer and/or LaunchServices app registry
  -> GUI list
```

Not proven:

```text
System Settings
  -> direct SELECT from TCC.access where service = kTCCServiceLocalNetwork
```

Run:

```bash
mse trace local-network ~/Desktop/mse-trace
```
