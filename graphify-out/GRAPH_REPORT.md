# Graph Report - finance-api  (2026-11-20)

## Corpus Check
- 61 files · ~18,968 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 7 file(s) not represented in the graph (top: (none) 4, .example 1, .ini 1)

## Summary
- 677 nodes · 1572 edges · 25 communities (17 shown, 8 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 30 edges (avg confidence: 0.93)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `0eefed6a`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- test_auth.py
- deps.py
- parsers/__init__.py
- test_overview.py
- intake.py
- test_api_auth.py
- test_schema.py
- routers/overview.py
- test_intake.py
- api
- ledger_view.py
- steps
- conftest.py
- test_errors.py
- errors.py
- health.py
- expected_send_money_fee_minor
- client
- main.py
- install_error_handlers

## God Nodes (most connected - your core abstractions)
1. `make_client()` - 33 edges
2. `login()` - 32 edges
3. `build_overview()` - 31 edges
4. `list_transactions()` - 24 edges
5. `ingest_sms()` - 22 edges
6. `send()` - 21 edges
7. `case()` - 19 edges
8. `parse_message()` - 18 edges
9. `Parsed` - 18 edges
10. `make_tx()` - 17 edges

## Surprising Connections (you probably didn't know these)
- `client()` --uses--> `ApiHeadersMiddleware`  [INFERRED]
  tests/test_errors.py → app/core/middleware.py
- `send_with_headers()` --calls--> `send()`  [INFERRED]
  app/core/middleware.py → tests/test_intake.py
- `test_docs_are_off_in_production()` --calls--> `create_app()`  [EXTRACTED]
  tests/test_config.py → app/main.py
- `test_after_midnight_in_nairobi_is_the_next_day()` --calls--> `today_nairobi()`  [EXTRACTED]
  tests/test_clock.py → app/core/clock.py
- `test_daytime_is_the_same_day()` --calls--> `today_nairobi()`  [EXTRACTED]
  tests/test_clock.py → app/core/clock.py

## Import Cycles
- None detected.

## Communities (25 total, 8 thin omitted)

### Community 0 - "test_auth.py"
Cohesion: 0.06
Nodes (60): run(), _user_id(), TooManyRequests, Unauthorized, _dummy_hash(), hash_password(), hash_token(), needs_rehash() (+52 more)

### Community 1 - "deps.py"
Cohesion: 0.05
Nodes (25): clear_session_cookie(), current_user(), ingest_user(), OriginNotAllowed, require_allowed_origin(), set_session_cookie(), login(), logout() (+17 more)

### Community 2 - "parsers/__init__.py"
Cohesion: 0.07
Nodes (25): looks_like_otp(), mask_phone(), month_number(), nairobi(), to_minor(), trailing_digits(), parse(), parse() (+17 more)

### Community 3 - "test_overview.py"
Cohesion: 0.08
Nodes (43): list_transactions(), _accounts(), build_overview(), _flows(), test_a_month_only_shows_its_own_days(), test_a_page_past_the_end_is_empty(), test_another_users_transactions_never_appear(), test_filter_by_account_finds_every_transaction_that_touches_it() (+35 more)

### Community 4 - "intake.py"
Cohesion: 0.06
Nodes (19): ingest(), normalise(), SmsIn, get_or_create_account(), provider_account(), provider_name(), _existing_totals(), _flag_for_review() (+11 more)

### Community 5 - "test_api_auth.py"
Cohesion: 0.09
Nodes (35): bearer(), login(), make_client(), sms(), test_a_login_code_is_acknowledged_but_never_stored(), test_a_malformed_login_is_a_validation_error(), test_a_retry_answers_200_and_counts_once(), test_a_revoked_token_is_refused() (+27 more)

### Community 6 - "test_schema.py"
Cohesion: 0.11
Nodes (29): add_entry(), make_account(), make_tx(), make_user(), post(), settle(), test_a_balanced_transaction_is_accepted(), test_a_message_cannot_attach_to_another_users_transaction() (+21 more)

### Community 7 - "routers/overview.py"
Cohesion: 0.11
Nodes (19): _month(), overview(), transactions(), today_nairobi(), parse_month(), Period, periods_for(), whole_month() (+11 more)

### Community 8 - "test_intake.py"
Cohesion: 0.14
Nodes (26): send_with_headers(), balances(), case(), count(), make_user(), send(), settle(), test_a_card_payment_is_spending_from_the_bank() (+18 more)

### Community 9 - "api"
Cohesion: 0.07
Nodes (31): build, depends_on, environment, healthcheck, ports, restart, condition, environment (+23 more)

### Community 10 - "ledger_view.py"
Cohesion: 0.23
Nodes (13): describe(), Entry, _escape_like(), _filters(), _ref(), asset(), test_a_broken_transaction_degrades_instead_of_crashing_the_screen(), test_a_transfer_names_both_accounts_and_has_no_category() (+5 more)

### Community 11 - "steps"
Cohesion: 0.11
Nodes (18): jobs, pytest, name, on, pull_request, push, permissions, contents (+10 more)

### Community 12 - "conftest.py"
Cohesion: 0.15
Nodes (8): alembic_config(), cheap_password_hashing(), client(), db(), migrated_engine(), session(), test_database_url(), test_migration_can_be_undone_and_redone()

### Community 15 - "health.py"
Cohesion: 0.22
Nodes (3): health(), ready(), ServiceUnavailable

### Community 16 - "expected_send_money_fee_minor"
Cohesion: 0.27
Nodes (5): expected_send_money_fee_minor(), fee_matches_tariff(), test_above_the_per_transaction_limit_there_is_no_fee_to_predict(), test_bands_every_source_agrees_on(), test_every_fee_in_the_real_samples_is_the_free_band()

### Community 17 - "client"
Cohesion: 0.33
Nodes (3): Conflict, client(), conflict()

### Community 19 - "install_error_handlers"
Cohesion: 0.53
Nodes (6): _body(), install_error_handlers(), handle_app_error(), handle_http(), handle_unexpected(), handle_validation()

## Knowledge Gaps
- **8 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ingest_sms()` connect `intake.py` to `test_intake.py`, `parsers/__init__.py`?**
  _High betweenness centrality (0.028) - this node is a cross-community bridge._
- **Should `test_auth.py` be split into smaller, more focused modules?**
  _Cohesion score 0.057729138166894664 - nodes in this community are weakly interconnected._
- **Why does `Parsed` connect `parsers/__init__.py` to `expected_send_money_fee_minor`, `intake.py`?**
  _High betweenness centrality (0.024) - this node is a cross-community bridge._
- **Should `deps.py` be split into smaller, more focused modules?**
  _Cohesion score 0.05311871227364185 - nodes in this community are weakly interconnected._
- **Why does `build_overview()` connect `test_overview.py` to `routers/overview.py`?**
  _High betweenness centrality (0.021) - this node is a cross-community bridge._
- **Should `parsers/__init__.py` be split into smaller, more focused modules?**
  _Cohesion score 0.07246376811594203 - nodes in this community are weakly interconnected._
- **Should `test_overview.py` be split into smaller, more focused modules?**
  _Cohesion score 0.08361581920903954 - nodes in this community are weakly interconnected._