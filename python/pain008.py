import json
import xml.etree.ElementTree as ET

from collections import OrderedDict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from jinja2 import select_autoescape
from jinja2.sandbox import SandboxedEnvironment

from pain001 import validate_scheme
from pain001.templates import DEFAULT_TEMPLATE_REGISTRY
from pain001.xml.validate_via_xsd import validate_xml_string_via_xsd


MESSAGE_TYPE = "pain.008.001.08"
NS_URI = f"urn:iso:std:iso:20022:tech:xsd:{MESSAGE_TYPE}"
NS = {"p": NS_URI}
ET.register_namespace("", NS_URI)

# Només s'utilitza en la validació de pain001. No s'afegeix al XML final.
_VALIDATION_BIC_SENTINEL = "BANKESMMXXX"


# Plantilla per a UN sol Document amb un GrpHdr i diversos PmtInf.
# Si prefereixes tenir-la en un fitxer extern, pots substituir
# _CUSTOM_TEMPLATE_SOURCE per la lectura del fitxer.
_CUSTOM_TEMPLATE_SOURCE = r'''<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.008.001.08"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
          xsi:schemaLocation="urn:iso:std:iso:20022:tech:xsd:pain.008.001.08 pain.008.001.08.xsd">
  <CstmrDrctDbtInitn>
    <GrpHdr>
      <MsgId>{{ id }}</MsgId>
      <CreDtTm>{{ date }}</CreDtTm>
      <NbOfTxs>{{ nb_of_txs }}</NbOfTxs>
      <CtrlSum>{{ ctrl_sum }}</CtrlSum>
      <InitgPty><Nm>{{ initiator_name }}</Nm></InitgPty>
    </GrpHdr>
    {% for group in payment_groups %}
    <PmtInf>
      <PmtInfId>{{ group.payment_information_id }}</PmtInfId>
      <PmtMtd>DD</PmtMtd>
      <BtchBookg>false</BtchBookg>
      <NbOfTxs>{{ group.nb_of_txs }}</NbOfTxs>
      <CtrlSum>{{ group.ctrl_sum }}</CtrlSum>
      <PmtTpInf>
        <SvcLvl><Cd>SEPA</Cd></SvcLvl>
        <SeqTp>{{ group.sequence_type }}</SeqTp>
      </PmtTpInf>
      <ReqdColltnDt>{{ group.requested_execution_date }}</ReqdColltnDt>
      <Cdtr><Nm>{{ group.creditor_name }}</Nm></Cdtr>
      <CdtrAcct><Id><IBAN>{{ group.creditor_account_IBAN }}</IBAN></Id></CdtrAcct>
      {% if group.creditor_agent_BIC %}
      <CdtrAgt><FinInstnId><BICFI>{{ group.creditor_agent_BIC }}</BICFI></FinInstnId></CdtrAgt>
      {% else %}
      <CdtrAgt><FinInstnId><Othr><Id>NOTPROVIDED</Id></Othr></FinInstnId></CdtrAgt>
      {% endif %}
      <ChrgBr>SLEV</ChrgBr>
      <CdtrSchmeId>
        <Id>
          <PrvtId>
            <Othr>
              <Id>{{ group.creditor_scheme_id }}</Id>
              <SchmeNm><Prtry>SEPA</Prtry></SchmeNm>
            </Othr>
          </PrvtId>
        </Id>
      </CdtrSchmeId>
      {% for tx in group.transactions %}
      <DrctDbtTxInf>
        <PmtId><EndToEndId>{{ tx.payment_id }}</EndToEndId></PmtId>
        <InstdAmt Ccy="{{ tx.payment_currency }}">{{ tx.payment_amount }}</InstdAmt>
        <DrctDbtTx>
          <MndtRltdInf>
            <MndtId>{{ tx.mandate_id }}</MndtId>
            <DtOfSgntr>{{ tx.date_of_signature }}</DtOfSgntr>
          </MndtRltdInf>
        </DrctDbtTx>
        {% if tx.debtor_agent_BIC %}
        <DbtrAgt><FinInstnId><BICFI>{{ tx.debtor_agent_BIC }}</BICFI></FinInstnId></DbtrAgt>
        {% else %}
        <DbtrAgt><FinInstnId><Othr><Id>NOTPROVIDED</Id></Othr></FinInstnId></DbtrAgt>
        {% endif %}
        <Dbtr><Nm>{{ tx.debtor_name }}</Nm></Dbtr>
        <DbtrAcct><Id><IBAN>{{ tx.debtor_account_IBAN }}</IBAN></Id></DbtrAcct>
        {% if tx.remittance_information %}
        <RmtInf><Ustrd>{{ tx.remittance_information }}</Ustrd></RmtInf>
        {% endif %}
      </DrctDbtTxInf>
      {% endfor %}
    </PmtInf>
    {% endfor %}
  </CstmrDrctDbtInitn>
</Document>
'''


def _s(value):
    return "" if value is None else str(value).strip()


def _optional(value):
    value = _s(value)
    return value if value else None


def _iso_date(value, field_name, row_number=None):
    text = _s(value)
    if not text:
        return ""

    candidates = [text, text.replace("/", "-"), text.replace(".", "-")]
    for candidate in candidates:
        try:
            if "T" in candidate:
                return datetime.fromisoformat(candidate).date().isoformat()
            if " " in candidate and len(candidate) >= 19:
                return datetime.fromisoformat(
                    candidate.replace(" ", "T", 1)
                ).date().isoformat()
            return date.fromisoformat(candidate).isoformat()
        except ValueError:
            continue

    where = f" de la fila {row_number}" if row_number else ""
    raise ValueError(
        f"{field_name}{where} ha de ser una data vàlida (YYYY-MM-DD). "
        f"Valor rebut: {text!r}"
    )


def _decimal_amount(value, row_number=None):
    text = _s(value).replace(",", ".")
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError):
        where = f" a la fila {row_number}" if row_number else ""
        raise ValueError(f"Import no vàlid{where}: {value!r}")

    if not amount.is_finite() or amount <= 0:
        where = f" a la fila {row_number}" if row_number else ""
        raise ValueError(f"L'import ha de ser positiu{where}: {value!r}")

    return amount.quantize(Decimal("0.01"))


def _rows_from_payload(payload):
    raw_rows = payload.get("rows", [])
    cfg = payload.get("config", {})

    if not raw_rows:
        raise ValueError("No hi ha cap fila de cobrament.")

    msg_id = (
        _s(cfg.get("message_id"))
        or "DD" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    )
    default_payment_info_id = (
        _s(cfg.get("payment_info_id")) or (msg_id[:30] + "-P1")
    )

    creditor_name = _s(cfg.get("creditor_name"))
    creditor_iban = _s(cfg.get("creditor_iban"))
    creditor_bic = _s(cfg.get("creditor_bic"))
    creditor_scheme_id = _s(cfg.get("creditor_scheme_id"))
    default_collection_date = _s(cfg.get("collection_date"))
    initiator_name = _s(cfg.get("initiator_name")) or creditor_name

    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    output = []

    for index, source in enumerate(raw_rows, start=1):
        row = {str(k).strip().lower(): _s(v) for k, v in source.items()}

        payment_info_id = (
            _s(row.get("payment_info_id"))
            or _s(row.get("pmtinfid"))
            or _s(row.get("pmt_inf_id"))
            or default_payment_info_id
        )
        if not payment_info_id:
            raise ValueError(f"Fila {index}: PmtInfId és obligatori.")
        if len(payment_info_id) > 35:
            raise ValueError(f"Fila {index}: PmtInfId supera els 35 caràcters.")

        payment_id = _s(row.get("payment_id")) or f"DD-{index:05d}"
        if len(payment_id) > 35:
            raise ValueError(f"Fila {index}: payment_id supera els 35 caràcters.")

        collection_date = _iso_date(
            row.get("collection_date") or default_collection_date,
            "collection_date",
            index,
        )
        mandate_signed_on = _iso_date(
            row.get("mandate_signed_on")
            or row.get("mandate_signature_date")
            or row.get("mandate_date_of_signature"),
            "mandate_signed_on",
            index,
        )

        c_name = row.get("creditor_name") or creditor_name
        c_iban = (
            row.get("creditor_account_iban")
            or row.get("creditor_iban")
            or creditor_iban
        )
        c_bic = (
            row.get("creditor_agent_bic")
            or row.get("creditor_bic")
            or creditor_bic
        )
        c_scheme = row.get("creditor_scheme_id") or creditor_scheme_id

        debtor_bic = row.get("debtor_bic") or row.get("debtor_agent_bic")
        remittance = row.get("remittance") or row.get("remittance_info")

        item = {
            "id": msg_id,
            "message_id": msg_id,
            "date": created_at,
            "initiator_name": initiator_name,
            "payment_id": payment_id,
            "end_to_end_id": payment_id,
            "payment_info_id": payment_info_id,
            "payment_information_id": payment_info_id,
            "requested_collection_date": collection_date,
            "execution_date": collection_date,
            "creditor_name": c_name,
            "creditor_account_IBAN": c_iban,
            "creditor_scheme_id": c_scheme,
            "creditor_agent_BIC": c_bic,
            "debtor_name": row.get("debtor_name", ""),
            "debtor_account_IBAN": (
                row.get("debtor_iban") or row.get("debtor_account_iban", "")
            ),
            "debtor_agent_BIC": debtor_bic,
            "payment_amount": _decimal_amount(row.get("amount"), index),
            "payment_currency": row.get("currency") or "EUR",
            "mandate_id": row.get("mandate_id", ""),
            "mandate_signed_on": mandate_signed_on,
            "date_of_signature": mandate_signed_on,
            "mandate_signature_date": mandate_signed_on,
            "mandate_date_of_signature": mandate_signed_on,
            "sequence_type": (row.get("sequence_type") or "OOFF").upper(),
            "charge_bearer": "SLEV",
            "remittance_info": remittance,
            "remittance_information": remittance,
        }
        output.append(item)

    return output


def _group_rows(rows):
    groups = OrderedDict()
    for row in rows:
        key = _s(row.get("payment_info_id") or row.get("payment_information_id"))
        groups.setdefault(key, []).append(row)
    return groups


def _payment_info_group_violations(rows):
    violations = []
    common_fields = (
        "requested_collection_date",
        "creditor_name",
        "creditor_account_IBAN",
        "creditor_scheme_id",
        "creditor_agent_BIC",
        "sequence_type",
    )

    for payment_info_id, group in _group_rows(rows).items():
        first = group[0]
        for row_number, row in enumerate(group[1:], start=2):
            for field in common_fields:
                if _s(first.get(field)) != _s(row.get(field)):
                    if field == "requested_collection_date":
                        message = (
                            f"PmtInfId '{payment_info_id}': només pot tenir "
                            "una data de cobrament. S'han trobat "
                            f"{first.get(field)} i {row.get(field)}."
                        )
                    else:
                        message = (
                            f"PmtInfId '{payment_info_id}': el camp '{field}' "
                            "té valors diferents dins del mateix grup."
                        )
                    violations.append({
                        "rule": "payment_info_group_mismatch",
                        "field": field,
                        "message": message,
                    })
                    break

    return violations


def _generation_violations(rows):
    violations = []
    for index, row in enumerate(rows, start=1):
        required = {
            "creditor_name": row.get("creditor_name"),
            "creditor_account_IBAN": row.get("creditor_account_IBAN"),
            "creditor_scheme_id": row.get("creditor_scheme_id"),
            "requested_collection_date": row.get("requested_collection_date"),
            "mandate_id": row.get("mandate_id"),
            "mandate_signed_on": row.get("mandate_signed_on"),
            "debtor_name": row.get("debtor_name"),
            "debtor_account_IBAN": row.get("debtor_account_IBAN"),
        }
        for field, value in required.items():
            if not _s(value):
                violations.append({
                    "rule": "generation_required",
                    "field": field,
                    "message": (
                        f"Fila {index}: el camp '{field}' és obligatori "
                        "per generar un pain.008.001.08."
                    ),
                })

        if row.get("sequence_type") not in {"FRST", "RCUR", "FNAL", "OOFF"}:
            violations.append({
                "rule": "sequence_type",
                "field": "sequence_type",
                "message": (
                    f"Fila {index}: sequence_type ha de ser FRST, RCUR, "
                    "FNAL o OOFF."
                ),
            })

        currency = _s(row.get("payment_currency")).upper()
        if len(currency) != 3 or not currency.isalpha():
            violations.append({
                "rule": "currency",
                "field": "payment_currency",
                "message": f"Fila {index}: codi de moneda no vàlid: {currency!r}.",
            })

    return violations


def _rows_for_scheme_validation(rows):
    checked = []
    for row in rows:
        item = dict(row)
        if not _s(item.get("creditor_agent_BIC")):
            item["creditor_agent_BIC"] = _VALIDATION_BIC_SENTINEL
        if not _s(item.get("debtor_agent_BIC")):
            item["debtor_agent_BIC"] = _VALIDATION_BIC_SENTINEL
        checked.append(item)
    return checked


def _validation_json(result):
    violations = []
    for item in getattr(result, "violations", []) or []:
        violations.append({
            "rule": getattr(item, "rule", ""),
            "field": getattr(item, "field", ""),
            "message": getattr(item, "message", str(item)),
        })
    return violations


def _all_violations(rows):
    result = validate_scheme(
        _rows_for_scheme_validation(rows),
        profile="sepa-sdd",
        message_type=MESSAGE_TYPE,
    )
    violations = _validation_json(result)
    violations.extend(_generation_violations(rows))
    violations.extend(_payment_info_group_violations(rows))
    return result, violations


def validate(payload_json):
    try:
        payload = json.loads(payload_json)
        rows = _rows_from_payload(payload)
        result, violations = _all_violations(rows)

        has_sequence_column = any(
            "sequence_type" in {str(k).strip().lower() for k in r.keys()}
            for r in payload.get("rows", [])
        )

        return json.dumps({
            "is_valid": bool(getattr(result, "is_valid", False)) and not violations,
            "rows": len(rows),
            "groups": len(_group_rows(rows)),
            "violations": violations,
            "sequence_type_defaulted_to_ooff": not has_sequence_column,
        })
    except Exception as exc:
        return json.dumps({
            "is_valid": False,
            "rows": 0,
            "groups": 0,
            "violations": [{
                "rule": "input_error",
                "field": "",
                "message": str(exc),
            }],
        })


def _build_template_data(rows):
    if not rows:
        raise ValueError("No hi ha files per generar.")

    payment_groups = []
    total_amount = Decimal("0.00")

    for payment_info_id, group_rows in _group_rows(rows).items():
        first = group_rows[0]
        transactions = []
        group_total = Decimal("0.00")

        for row in group_rows:
            amount = Decimal(str(row["payment_amount"])).quantize(Decimal("0.01"))
            group_total += amount
            tx = {
                "payment_id": row["payment_id"],
                "payment_amount": f"{amount:.2f}",
                "payment_currency": row["payment_currency"],
                "mandate_id": row["mandate_id"],
                "date_of_signature": row["mandate_signed_on"],
                "debtor_name": row["debtor_name"],
                "debtor_account_IBAN": row["debtor_account_IBAN"],
                "debtor_agent_BIC": row.get("debtor_agent_BIC") or "",
                "remittance_information": row.get("remittance_information") or "",
            }
            transactions.append(tx)

        total_amount += group_total
        payment_groups.append({
            "payment_information_id": payment_info_id,
            "nb_of_txs": len(group_rows),
            "ctrl_sum": f"{group_total:.2f}",
            "sequence_type": first["sequence_type"],
            "requested_execution_date": first["requested_collection_date"],
            "creditor_name": first["creditor_name"],
            "creditor_account_IBAN": first["creditor_account_IBAN"],
            "creditor_scheme_id": first["creditor_scheme_id"],
            "creditor_agent_BIC": first.get("creditor_agent_BIC") or "",
            "transactions": transactions,
        })

    return {
        "id": rows[0]["id"],
        "date": rows[0]["date"],
        "nb_of_txs": len(rows),
        "ctrl_sum": f"{total_amount:.2f}",
        "initiator_name": rows[0]["initiator_name"],
        "payment_groups": payment_groups,
    }


def _render_xml(rows):
    env = SandboxedEnvironment(
        autoescape=select_autoescape(
            enabled_extensions=("xml",),
            default_for_string=True,
        )
    )
    template = env.from_string(_CUSTOM_TEMPLATE_SOURCE)
    return template.render(**_build_template_data(rows))


def _clean_optional_xml(xml):
    """Elimina nodes opcionals buits i normalitza la serialització."""
    root = ET.fromstring(xml)

    for tx in root.findall(".//p:DrctDbtTxInf", NS):
        rmt = tx.find("p:RmtInf", NS)
        if rmt is not None:
            ustrd = rmt.find("p:Ustrd", NS)
            if ustrd is None or not _s(ustrd.text):
                tx.remove(rmt)

    return ET.tostring(
        root,
        encoding="unicode",
        xml_declaration=True,
    )


def _verify_payment_info_groups(xml, rows):
    root = ET.fromstring(xml)
    init = root.find("p:CstmrDrctDbtInitn", NS)
    if init is None:
        raise RuntimeError("No s'ha trobat CstmrDrctDbtInitn.")

    expected = {}
    for payment_info_id, group in _group_rows(rows).items():
        expected[payment_info_id] = (
            _s(group[0].get("requested_collection_date")),
            len(group),
        )

    actual = {}
    for pmt in init.findall("p:PmtInf", NS):
        pid = pmt.findtext("p:PmtInfId", namespaces=NS)
        collection_date = pmt.findtext("p:ReqdColltnDt", namespaces=NS)
        count = pmt.findtext("p:NbOfTxs", namespaces=NS)

        if not pid:
            raise RuntimeError("S'ha generat un PmtInf sense PmtInfId.")
        if pid in actual:
            raise RuntimeError(f"El PmtInfId '{pid}' apareix duplicat al XML.")

        actual[pid] = (collection_date, int(count or 0))

    if expected != actual:
        raise RuntimeError(
            "Els blocs PmtInf generats no coincideixen amb els esperats. "
            f"Esperats: {expected}. Generats: {actual}."
        )

    header = init.find("p:GrpHdr", NS)
    if header is None:
        raise RuntimeError("No s'ha trobat GrpHdr.")

    header_count = int(header.findtext("p:NbOfTxs", default="0", namespaces=NS))
    if header_count != len(rows):
        raise RuntimeError(
            f"NbOfTxs global incorrecte: {header_count}. "
            f"S'esperaven {len(rows)}."
        )

    header_sum = Decimal(
        header.findtext("p:CtrlSum", default="0", namespaces=NS)
    )
    expected_sum = sum(
        (Decimal(str(row["payment_amount"])) for row in rows),
        Decimal("0.00"),
    )
    if header_sum != expected_sum:
        raise RuntimeError(
            f"CtrlSum global incorrecte: {header_sum}. "
            f"S'esperava {expected_sum}."
        )


def generate(payload_json):
    try:
        payload = json.loads(payload_json)
        rows = _rows_from_payload(payload)

        schema_template = DEFAULT_TEMPLATE_REGISTRY.get_template(MESSAGE_TYPE)
        if schema_template is None:
            raise RuntimeError(f"No s'ha trobat l'XSD per a {MESSAGE_TYPE}.")

        result, violations = _all_violations(rows)
        if not getattr(result, "is_valid", False) or violations:
            preview = ""
            try:
                preview = _clean_optional_xml(_render_xml(rows))
            except Exception:
                pass
            return json.dumps({
                "success": False,
                "message_type": MESSAGE_TYPE,
                "violations": violations or ["Les dades no superen la validació SEPA."],
                "xml_preview": preview,
                "rows": len(rows),
                "groups": len(_group_rows(rows)),
            })

        # Un únic render de tota la plantilla amb tots els payment_groups.
        xml = _clean_optional_xml(_render_xml(rows))

        _verify_payment_info_groups(xml, rows)

        if not validate_xml_string_via_xsd(xml, schema_template.xsd_path):
            raise RuntimeError(
                "El XML final no supera la validació XSD de pain.008.001.08. "
                "Revisa especialment l'ordre dels elements i els agents bancaris."
            )

        return json.dumps({
            "success": True,
            "message_type": MESSAGE_TYPE,
            "xml": xml,
            "xml_preview": xml,
            "rows": len(rows),
            "groups": len(_group_rows(rows)),
            "violations": [],
        })

    except Exception as exc:
        preview = ""
        try:
            if "rows" in locals() and rows:
                preview = _clean_optional_xml(_render_xml(rows))
        except Exception:
            pass

        return json.dumps({
            "success": False,
            "message_type": MESSAGE_TYPE,
            "violations": [str(exc)],
            "xml_preview": preview,
            "rows": len(rows) if "rows" in locals() else 0,
            "groups": len(_group_rows(rows)) if "rows" in locals() and rows else 0,
        })
