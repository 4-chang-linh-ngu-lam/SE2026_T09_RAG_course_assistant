# 06 — Security, tenancy and service boundaries

## Controls already present in the RAG library

- TextRetriever requires an authorize callback; absence, callback exceptions, non-set results, unknown child IDs or malformed scopes deny retrieval.
- Retrieval narrows candidates to authorized and retrieval_eligible child IDs before dense/BM25 search, then re-reads authorization and raises AccessChangedError if the allowed snapshot changed before return.
- TextRagPipeline/RagPipeline re-check the caller snapshot around generation; revoked access during generation discards the result.
- Index and embedding manifests explicitly say they do not grant authorization.
- source_quotes builds bounded exact quote enums from evidence and maps exact spans; cited IDs must refer to supplied evidence.
- System prompts label evidence untrusted and say not to follow instructions inside it. This is a mitigation, not a prompt-injection security proof.
- Model adapters bind local artifacts, tokenizer, model/server SHA and profile identity; these adapters do not download models.

## Gaps and risks

| Finding | Evidence | Impact / classification |
|---|---|---|
| No production auth provider is wired | authorize is a required injected callback; no Core client in services/rag | BLOCKER: RAG cannot establish identity/current class permission itself |
| No Document grant/content contract | no services/document; Task17 only has draft endpoints | BLOCKER: cannot know authorized source versions or revocation state |
| Index has no tenant/class metadata | TextDocument and main bundle do not contain school_id/class_id/owner_id; source_id is caller-defined | HIGH: safe multi-tenant filtering needs an authoritative mapping layer |
| Canonical ACL is metadata only | source_acl is caller-supplied in Canonical; index manifests say grants_authorization=false | HIGH: do not use Canonical ACL fields as authorization |
| Canonical v2 publisher missing | current canonical emitter is idp-canonical-1; v2 harness imports absent idp.publish | HIGH: README's v2 path is not executable from tracked source |
| Low-level answer trace carries raw generation text | services/rag/pipeline.py returns raw_generation_text and primary_raw_generation_text in trace | HIGH: future API/log adapter must strip these fields; never expose/log raw prompt/answer trace |
| Semantic correctness not certified by default | result flags semantic_grounding_verified/certifies_answer_correctness false; optional verifier is not mandatory | HIGH: citation-position match is not proof of entailment |
| Conversation privacy/retention absent | no AI store; OD-02 retention pending | BLOCKER: no persistent Tutor production data until policy is approved |
| Assessment lock absent | no Learning service/D6 endpoint | BLOCKER: Tutor must fail closed when official-assessment status cannot be verified |
| Upload/archive expansion limits need service-level review | file size/page/pixel limits exist; Office ZIP preflight reads archive names but no shared Document quarantine service | REVIEW: archive-bomb/malware policy belongs to Document service |

## Required ownership boundary

- Core owns identity, roles, class membership/assignment and current access decisions.
- Document owns original file, version, grant/revoke and source/citation locators.
- AI owns private conversation/message state and derived RAG index/retrieval metadata.
- Learning owns official Assessment state and deadline; AI cannot infer it from browser flags.
- Web is a client/gateway. It must not accept user_id/class membership/source grants as trusted request-body claims.
- No SQL or foreign keys across service-owned schemas. Internal calls use scoped service credentials and current permissions.
- Admin/teachers do not get default access to a Student's private conversation.

## Exact authorization requirement for future integration

For a new Tutor turn, resolve the caller via Core, require current use_ai_tutor access for the exact class, fetch the current Document grants and matching successful versions, check D6 through Learning, build the authorized chunk-ID set, then call the RAG pipeline. Revalidate grants/access before returning citations. If any dependency errors or returns an unknown status, fail closed.

For history reads, verify conversation owner and class association, then use the separate read_own_history action; history permission must not authorize new retrieval. If a source grant is revoked, keep only history allowed by H4 and mask source quotes/links that no longer have permission.

## Integration readiness by service

| Service | Required role | Current evidence | Blocking item |
|---|---|---|---|
| Core | actor identity and current class authorization | internal access-check exists; actions include use_ai_tutor/read_own_history | AI Service client/auth scope and endpoint contract not implemented |
| Document | source/version/grant/citation truth | Task17 describes draft model/routes only | no service or active-grant/content API |
| Learning | official Assessment state for D6 | Business Rule D6 / TASK-019 | no service/API, so production Tutor must deny new turns |
| AI | conversation owner, RAG orchestration, generated answer | no services/ai | runtime, schema, API and model not implemented |
| Web | same-origin proxy and product adapter | live Tutor methods return 503 and route is hidden | no AI upstream/operation allowlist/decoder |
