# Client Deployment

## Best Client-Ready Shape

Do not ship this as a browser extension first.

Best order of implementation:

1. Cross-platform local runner
2. Optional small desktop UI
3. Optional Claude-assisted manual entrypoint
4. OS-native scheduler or hosted runner

## Why Not a Browser Extension First

This workflow needs all of these at once:

- authenticated browser automation
- downloading files to disk
- reading multiple CSVs
- joining and appending local files
- running on demand or on a schedule

Extensions are weaker at local filesystem orchestration and unattended scheduling.

## Best Recommendation

For a client that may be on Windows or Mac:

1. keep the existing pipeline as the core engine
2. package it as a cross-platform local runner
3. optionally add a small desktop UI
4. optionally expose a Claude/Desktop skill as a manual trigger

## Claude Fit

Claude/Desktop is a good front door:

- `Run Ryan report`
- `Download Axon reports and append Ryan report`

But Claude should not be the only runtime or scheduling layer.
