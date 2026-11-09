# Radar Checks — team-tower, "before" (2026-11-09 22:20Z)

Cluster `tower`, namespace `team-tower`, right after the first GitOps deploy (`app` image `cb1f95e` → `a0e730e`).
Source: Radar MCP `get_cluster_audit` + `issues` (the Radar Cloud UI screenshot is added next to this file when captured).

**Live issues:** 0.

**Posture findings (4, all medium, all on `Deployment/team-tower/app`):**

| Category | Check | Finding | Planned fix |
|---|---|---|---|
| Security | automountServiceAccountToken | Service account token is auto-mounted | `automountServiceAccountToken: false` (the gateway never calls the API) |
| Security | readOnlyRootFs | Container `app` root filesystem is writable | `readOnlyRootFilesystem: true` + `emptyDir` at `/tmp` |
| Reliability | missingPDB | 2 replicas, no PodDisruptionBudget | PDB `maxUnavailable: 1` |
| Reliability | missingTopologySpread | 2 replicas, no topology spread | `topologySpreadConstraints` on `kubernetes.io/hostname`, `ScheduleAnyway` |
