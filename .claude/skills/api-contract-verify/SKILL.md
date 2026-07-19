---
name: api-contract-verify
description: Use automatically before writing any code that calls a third-party API, framework internal, or library function whose exact request/response shape hasn't been confirmed in this conversation — verifies the real format via docs or search instead of assuming one.
allowed-tools: Read, Grep, WebSearch, WebFetch
---

# API Contract Verify

Before writing integration code against an external API (Upstash REST, 
a payment API, an LLM provider, etc.) or a framework's less-common 
constructor/parameter (e.g. FastAPI response classes, ORM methods):

1. Do not construct the request/response shape from memory or pattern-matching alone.
2. If official docs haven't been fetched in this conversation, use WebSearch 
   and WebFetch to read the current documentation for that exact call before 
   writing code.
3. If uncertain even after checking, say so explicitly rather than guessing 
   silently — flag the uncertainty to the user.
4. When reviewing existing code, use Read/Grep to check any external API call 
   for whether it matches the documented format currently, not just whether 
   it looks reasonable.