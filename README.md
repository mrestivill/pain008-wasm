# pain.008 GitHub Pages — V4.5

V4.5 fixes optional BIC handling and makes validation strictly manual.

- Empty creditor/debtor BICs are omitted from generated XML.
- SEPA-SDD scheme validation uses an internal valid-format sentinel only when a BIC is absent, preventing `None` from being validated as a BIC. The sentinel is never written to XML.
- The page starts in `Not validated` state.
- Loading sample/CSV or editing any field does not execute validation.
- The `Validate` button is the only action that runs `pain001.validate_scheme`.
- XML generation remains disabled until the current data has been successfully validated.
- `try-pain008.js?v=45` cache-busts the browser/GitHub Pages copy of the JavaScript.

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


## V4.8 generation behavior

- Example `mandate_signed_on` uses 2026-10-07.
- `collection_date` and `mandate_signed_on` are parsed to ISO `YYYY-MM-DD` before XML generation.
- The pain001 template mapping accepts `mandate_signed_on`, `mandate_signature_date`, `mandate_date_of_signature`, and `date_of_signature`.
- Generate XML renders a raw XML preview even when scheme/XSD validation fails. The preview is never enabled for XML/Q1X download unless the final generated XML passes XSD validation.
- `generate_xml_string()` remains the final validated generation path; raw preview is rendered separately because pain001's documented function returns only generated-and-validated XML.
