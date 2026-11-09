---
title: Elasticsearch mapping change checklist
description: Any change to an index mapping must be safe to apply to a live index or ship with a reindex plan.
when: Files under spark/es/mappings/ change, or code changes an index name, alias, or the embedding model or dimension.
actions:
  - Post a checklist comment on the PR with the items below.
  - Request changes if an existing field's type changed without a new index version and a reindex step.
---

Checklist to post:

- [ ] Only additive changes (new fields) on existing indices; an existing field's `type`, `analyzer`, `dims` or `similarity` is never changed in place.
- [ ] A breaking change uses a new versioned index (`moments-v2`), an alias switch and a reindex step in the PR.
- [ ] `embedding` is still `dense_vector`, `dims: 384`, `similarity: cosine`, `index: true`, matching `EMBED_MODEL_PATH`.
- [ ] Moments still require `talk_id`, `room`, `t_start`, `t_end`, `@timestamp`, with `dynamic: strict`.
- [ ] The interests percolator index maps every field its stored queries reference.
- [ ] Mappings are loaded from `spark/es/mappings/*.json`, not duplicated inline in code.
