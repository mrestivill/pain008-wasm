import json
from datetime import datetime, timezone
from pain001 import generate_xml_string, validate_scheme
from pain001.constants import TEMPLATES_DIR

MESSAGE_TYPE = "pain.008.001.08"


def _s(value):
    return "" if value is None else str(value).strip()


def _rows_from_payload(payload):
    raw_rows = payload.get("rows", [])
    cfg = payload.get("config", {})
    if not raw_rows:
        raise ValueError("No hi ha cap fila de cobrament.")

    default_seq = "OOFF"
    out = []
    msg_id = _s(cfg.get("message_id")) or "DD" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    creditor_name = _s(cfg.get("creditor_name"))
    creditor_iban = _s(cfg.get("creditor_iban"))
    creditor_bic = _s(cfg.get("creditor_bic"))
    creditor_scheme_id = _s(cfg.get("creditor_scheme_id"))
    default_collection_date = _s(cfg.get("collection_date"))
    initiator_name = _s(cfg.get("initiator_name")) or creditor_name

    for index, src in enumerate(raw_rows, start=1):
        row = {str(k).strip().lower(): _s(v) for k, v in src.items()}
        sequence_type = _s(row.get("sequence_type")) or default_seq
        payment_id = _s(row.get("payment_id")) or f"DD-{index:05d}"
        collection_date = _s(row.get("collection_date")) or default_collection_date

        c_name = _s(row.get("creditor_name")) or creditor_name
        c_iban = _s(row.get("creditor_account_iban")) or _s(row.get("creditor_iban")) or creditor_iban
        c_bic = _s(row.get("creditor_agent_bic")) or _s(row.get("creditor_bic")) or creditor_bic
        c_scheme = _s(row.get("creditor_scheme_id")) or creditor_scheme_id

        out.append({
            "id": msg_id,
            "message_id": msg_id,
            "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "initiator_name": initiator_name,
            "payment_id": payment_id,
            "end_to_end_id": payment_id,
            "execution_date": collection_date,
            "requested_collection_date": collection_date,
            "creditor_name": c_name,
            "creditor_account_iban": c_iban,
            "creditor_agent_bic": c_bic,
            "creditor_scheme_id": c_scheme,
            "debtor_name": _s(row.get("debtor_name")),
            "debtor_account_iban": _s(row.get("debtor_iban")) or _s(row.get("debtor_account_iban")),
            "debtor_agent_bic": _s(row.get("debtor_bic")) or _s(row.get("debtor_agent_bic")),
            "payment_amount": _s(row.get("amount")),
            "payment_currency": _s(row.get("currency")) or "EUR",
            "mandate_id": _s(row.get("mandate_id")),
            "mandate_signed_on": _s(row.get("mandate_signed_on")) or _s(row.get("mandate_signature_date")),
            "sequence_type": sequence_type,
            "charge_bearer": "SLEV",
            "remittance_info": _s(row.get("remittance")) or _s(row.get("remittance_info")),
        })
    return out


def _validation_json(result):
    violations = []
    for item in getattr(result, "violations", []) or []:
        violations.append({
            "rule": getattr(item, "rule", ""),
            "field": getattr(item, "field", ""),
            "message": getattr(item, "message", str(item)),
        })
    return violations


def validate(payload_json):
    payload = json.loads(payload_json)
    rows = _rows_from_payload(payload)
    result = validate_scheme(rows, profile="sepa-sdd")
    violations = _validation_json(result)
    has_sequence_column = any("sequence_type" in r for r in payload.get("rows", []))
    return json.dumps({
        "is_valid": bool(getattr(result, "is_valid", False)),
        "rows": len(rows),
        "violations": violations,
        "sequence_type_defaulted_to_ooff": not has_sequence_column,
    })


def generate(payload_json):
    payload = json.loads(payload_json)
    rows = _rows_from_payload(payload)
    result = validate_scheme(rows, profile="sepa-sdd")
    violations = _validation_json(result)
    if not getattr(result, "is_valid", False):
        return json.dumps({"success": False, "violations": violations})

    bundle = TEMPLATES_DIR / MESSAGE_TYPE
    xml = generate_xml_string(
        rows,
        MESSAGE_TYPE,
        str(bundle / "template.xml"),
        str(bundle / f"{MESSAGE_TYPE}.xsd"),
    )
    return json.dumps({
        "success": True,
        "message_type": MESSAGE_TYPE,
        "xml": xml,
        "rows": len(rows),
    })
