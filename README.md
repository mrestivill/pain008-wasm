# pain.008 GitHub Pages — Pyodide + pain001 v4.2

100% client-side SEPA Direct Debit generator.

## Stack
- Pyodide 0.314.0.7
- Python WASM, single-thread
- pain001 0.0.72
- pain.008.001.08 / SEPA SDD
- GitHub Pages + GitHub Actions

## Important v4.2 fix
`pain001.validate_scheme()` expects canonical identifier keys with uppercase suffixes:
- `debtor_account_IBAN`
- `creditor_account_IBAN`
- `debtor_agent_BIC`
- `creditor_agent_BIC`

The previous version passed lowercase `*_iban` / `*_bic` keys directly to scheme validation, causing every debtor and creditor IBAN to be reported as invalid. v4.2 passes the canonical keys.

## Sequence type
If the CSV has no `sequence_type` column, `OOFF` is used. Blank values also default to `OOFF`.

## Q1X
The Q1X download contains the same generated `pain.008.001.08` XML and uses a `.Q1X` extension, matching the supplied bank example format.


## Generation requirements
For pain.008.001.08 SEPA Direct Debit generation, each transaction must provide `mandate_id` and `mandate_signed_on`. `debtor_bic` and `remittance` are optional and are omitted when empty. `PmtInfId` is generated automatically.

### Validació manual
La pàgina no executa la validació automàticament en obrir-se, carregar un CSV, usar el sample ni modificar camps. Cal prémer **Validate** per executar `pain001` i la validació SEPA/XSD. Si després de validar es modifica qualsevol dada, la validació anterior queda invalidada i cal tornar a prémer **Validate** abans de generar l'XML.

Els camps opcionals buits, com els BIC, s'ometen del payload enviat a `pain001`; no s'envia `None` com a valor.
