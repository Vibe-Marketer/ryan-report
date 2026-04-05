# PRD: Client-Ready Ryan Report Runner

## Problem

The current implementation works locally for an operator who can run Python scripts and manage downloaded files, but it is not yet packaged for a client-friendly install or a one-click experience.

## Goal

Turn the current local automation into a client-ready local runner with:

- one-click manual execution
- scheduled execution
- browser download integration
- unresolved serial review
- optional Claude/Desktop trigger

## Users

- internal operator
- client-side coordinator
- future Claude/Desktop operator

## Functional Requirements

1. The app must run on macOS and Windows.
2. The app must support manual execution.
3. The app must support scheduled execution.
4. The app must support browser-based Axon report downloads.
5. The app must build and append Ryan reports using the current logic.
6. The app must expose unresolved serials for manual correction.
7. The app must persist operator overrides.
8. The app should support a Claude/Desktop trigger layer.

## Non-Goals

- hosted multi-tenant SaaS
- browser extension as the primary architecture
- replacing the local file-based pipeline immediately

## Success Criteria

- client can run the workflow without editing Python directly
- scheduled runs work on both Mac and Windows
- unresolved serial handling is visible and recoverable
- current build accuracy is preserved

## Deliverables

- packaged local runner
- minimal desktop UI
- config UI for browser/profile/download folder
- unresolved serial review UI
- documented Claude trigger pattern
