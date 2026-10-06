# pain.008 GitHub Pages — Pyodide + pain001

Versió **100% client-side** del generador/validador `pain.008.001.08`.

## Arquitectura

```text
CSV
 ↓
JavaScript UI
 ↓
Pyodide (Python WASM)
 ↓
pain001 0.0.72
 ↓
SEPA SDD validation + bundled XSD
 ↓
pain.008.001.08 XML
 ↓
Download XML / Download Q1X
```

No hi ha FastAPI, Render, Docker ni servidor propi. GitHub Pages només serveix els fitxers estàtics. Python s'executa dins del navegador.

`pain001` publica suport per `pain.008.001.08` i el seu generador en memòria valida l'XML contra l'XSD inclòs al paquet. La validació `sepa-sdd` també comprova les regles de l'esquema SEPA. Consulta la documentació oficial abans d'usar el fitxer amb un banc. 

## Important sobre Pyodide

El primer carregat necessita internet perquè el navegador descarrega Pyodide i `pain001` des del CDN/PyPI. Després, el processament de les dades és local al navegador. Aquest repositori no inclou una còpia del wheel ni de totes les dependències de Python.

## CSV

Columnes mínimes del frontend:

- `payment_id`
- `amount`
- `currency`
- `mandate_id`
- `collection_date`
- `debtor_name`
- `debtor_iban`

Opcional:

- `sequence_type` (`FRST`, `RCUR`, `OOFF`, `FNAL`)
- `debtor_bic`
- `remittance`
- dades del creditor per fila (`creditor_name`, `creditor_account_iban`, `creditor_agent_bic`, `creditor_scheme_id`)

Si no existeix `sequence_type`, el codi assigna `OOFF` a totes les files. Si existeix però una fila està buida, també.

## GitHub Pages

1. Puja el contingut del ZIP a un repositori.
2. Fes push a `main`.
3. A **Settings → Pages**, selecciona **GitHub Actions**.
4. El workflow `.github/workflows/pages.yml` desplega els fitxers estàtics.

## Q1X

El botó **Download Q1X** no transforma l'XML: descarrega exactament el mateix `pain.008.001.08` validat per `pain001`, però amb extensió `.Q1X`. Això és coherent amb el fitxer de mostra proporcionat, que porta `pain.008.001.08` com a namespace XML.

## Font de l'enginy

- Pain001: https://github.com/sebastienrousseau/pain001
- PyPI: https://pypi.org/project/pain001/
- Pyodide: https://pyodide.org/
