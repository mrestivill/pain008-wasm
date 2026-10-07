import json
from datetime import date, datetime, timezone
from pain001 import generate_xml_string, validate_scheme
from pain001.xml.validate_via_xsd import validate_xml_string_via_xsd
from pain001.templates import DEFAULT_TEMPLATE_REGISTRY

MESSAGE_TYPE = "pain.008.001.08"


def _s(value):
    return "" if value is None else str(value).strip()


def _optional(value):
    value = _s(value)
    return value if value else None


def _iso_date(value, field_name):
    """Normalize common CSV/UI date formats to the XSD lexical date form YYYY-MM-DD."""
    raw = _s(value)
    if not raw:
        return ""
    candidates = (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y/%m/%d",
    )
    for fmt in candidates:
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass
    # Accept an ISO datetime and keep only its date component.
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        raise ValueError(
            f"{field_name}: data no vàlida '{raw}'. Utilitza YYYY-MM-DD (per exemple 2026-10-07)."
        )


def _today_iso():
    return date.today().isoformat()


# pain001 0.0.72 can run the SEPA-SDD scheme BIC check even when an optional
# BIC key is absent, in which case the internal check may receive None. The
# XML/XSD allows the agent BIC element to be omitted, so for scheme validation
# only we use a valid-format internal sentinel. The real row never contains
# this value and generation still omits an empty BIC.
_VALIDATION_BIC_SENTINEL = "BANKESMMXXX"


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


def _rows_from_payload(payload):
    raw_rows = payload.get("rows", [])
    cfg = payload.get("config", {})
    if not raw_rows:
        raise ValueError("No hi ha cap fila de cobrament.")

    default_seq = "OOFF"
    out = []
    msg_id = _s(cfg.get("message_id")) or "DD" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    payment_info_id = _s(cfg.get("payment_info_id")) or (msg_id[:30] + "-P1")
    creditor_name = _s(cfg.get("creditor_name"))
    creditor_iban = _s(cfg.get("creditor_iban"))
    creditor_bic = _s(cfg.get("creditor_bic"))
    creditor_scheme_id = _s(cfg.get("creditor_scheme_id"))
    default_collection_date = _iso_date(cfg.get("collection_date"), "collection_date") if _s(cfg.get("collection_date")) else ""
    initiator_name = _s(cfg.get("initiator_name")) or creditor_name

    for index, src in enumerate(raw_rows, start=1):
        row = {str(k).strip().lower(): _s(v) for k, v in src.items()}
        sequence_type = _s(row.get("sequence_type")) or default_seq
        payment_id = _s(row.get("payment_id")) or f"DD-{index:05d}"
        collection_date = _iso_date(row.get("collection_date"), f"Fila {index} collection_date") if _s(row.get("collection_date")) else default_collection_date

        c_name = _s(row.get("creditor_name")) or creditor_name
        c_iban = _s(row.get("creditor_account_iban")) or _s(row.get("creditor_iban")) or creditor_iban
        c_bic = _s(row.get("creditor_agent_bic")) or _s(row.get("creditor_bic")) or creditor_bic
        c_scheme = _s(row.get("creditor_scheme_id")) or creditor_scheme_id

        item = {
            "id": msg_id,
            "message_id": msg_id,
            "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "initiator_name": initiator_name,
            "payment_id": payment_id,
            "payment_info_id": payment_info_id,
            "end_to_end_id": payment_id,
            "execution_date": collection_date,
            "requested_collection_date": collection_date,
            "creditor_name": c_name,
            "creditor_account_IBAN": c_iban,
            "creditor_scheme_id": c_scheme,
            "debtor_name": _s(row.get("debtor_name")),
            "debtor_account_IBAN": _s(row.get("debtor_iban")) or _s(row.get("debtor_account_iban")),
            "payment_amount": _s(row.get("amount")),
            "payment_currency": _s(row.get("currency")) or "EUR",
            "mandate_id": _s(row.get("mandate_id")),
            "sequence_type": sequence_type,
            "charge_bearer": "SLEV",
        }

        mandate_signed_on = _s(row.get("mandate_signed_on")) or _s(row.get("mandate_signature_date"))
        if mandate_signed_on:
            mandate_signed_on = _iso_date(mandate_signed_on, f"Fila {index} mandate_signed_on")
        optional_fields = {
            "creditor_agent_BIC": _optional(c_bic),
            "debtor_agent_BIC": _optional(_s(row.get("debtor_bic")) or _s(row.get("debtor_agent_bic"))),
            "mandate_signed_on": _optional(mandate_signed_on),
            "remittance_info": _optional(_s(row.get("remittance")) or _s(row.get("remittance_info"))),
        }
        item.update({key: value for key, value in optional_fields.items() if value is not None})

        # Keep both the current canonical vocabulary and the legacy/template
        # spellings used by some pain001 0.0.72 Jinja templates.
        item["payment_information_id"] = payment_info_id
        if "mandate_signed_on" in item:
            item["mandate_signature_date"] = item["mandate_signed_on"]
        if "remittance_info" in item:
            item["remittance_information"] = item["remittance_info"]
        if c_bic:
            item["creditor_agent_bic"] = c_bic
        if _s(row.get("debtor_bic")) or _s(row.get("debtor_agent_bic")):
            item["debtor_agent_bic"] = _s(row.get("debtor_bic")) or _s(row.get("debtor_agent_bic"))
        out.append(item)
    return out


def _generation_violations(rows):
    violations = []
    for index, row in enumerate(rows, start=1):
        required = {
            "mandate_id": row.get("mandate_id"),
            "mandate_signed_on": row.get("mandate_signed_on"),
            "debtor_name": row.get("debtor_name"),
            "debtor_account_IBAN": row.get("debtor_account_IBAN"),
            "requested_collection_date": row.get("requested_collection_date"),
        }
        for field, value in required.items():
            if not _s(value):
                violations.append({
                    "rule": "generation_required",
                    "field": field,
                    "message": f"Fila {index}: el camp '{field}' és obligatori per generar un pain.008.001.08 vàlid."
                })
    return violations


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
    result = validate_scheme(_rows_for_scheme_validation(rows), profile="sepa-sdd", message_type=MESSAGE_TYPE)
    violations = _validation_json(result)
    violations.extend(_generation_violations(rows))
    has_sequence_column = any("sequence_type" in r for r in payload.get("rows", []))
    return json.dumps({
        "is_valid": bool(getattr(result, "is_valid", False)) and not violations,
        "rows": len(rows),
        "violations": violations,
        "sequence_type_defaulted_to_ooff": not has_sequence_column,
    })


def _clean_optional_xml(xml):
    """Remove optional empty agent/remittance nodes before final XSD validation."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml)
    ns = {"p": f"urn:iso:std:iso:20022:tech:xsd:{MESSAGE_TYPE}"}
    for parent_path, tag in [
        (".//p:DbtrAgt/p:FinInstnId", "BICFI"),
        (".//p:CdtrAgt/p:FinInstnId", "BICFI"),
        (".//p:RmtInf", "Ustrd"),
    ]:
        for parent in root.findall(parent_path, ns):
            child = parent.find(f"p:{tag}", ns)
            if child is not None and not _s(child.text):
                parent.remove(child)
                # Remove now-empty wrapper where it is optional.
                if len(parent) == 0 and parent.tag.endswith("RmtInf"):
                    for tx in root.findall(".//p:DrctDbtTxInf", ns):
                        for rmt in list(tx):
                            if rmt is parent:
                                tx.remove(rmt)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def generate(payload_json):
    payload = json.loads(payload_json)
    rows = _rows_from_payload(payload)
    try:
        result = validate_scheme(
            _rows_for_scheme_validation(rows),
            profile="sepa-sdd",
            message_type=MESSAGE_TYPE,
        )
        violations = _validation_json(result)
        violations.extend(_generation_violations(rows))
    except Exception as e:
        return json.dumps({"success": False, "violations": [str(e)], "rows": len(rows)})

    if not getattr(result, "is_valid", False) or violations:
        return json.dumps({"success": False, "violations": violations, "rows": len(rows)})

    template = DEFAULT_TEMPLATE_REGISTRY.get_template(MESSAGE_TYPE)
    if template is None:
        return json.dumps({
            "success": False,
            "violations": [f"La versió {MESSAGE_TYPE} no està registrada."],
            "rows": len(rows),
        })

    try:
        # The bundled 0.0.72 template expects a BIC node when the agent block
        # is rendered. Use the validation-only sentinel here; it is removed from
        # the final XML when the user's BIC is empty.
        render_rows = []
        for row in rows:
            item = dict(row)
            if not _s(item.get("creditor_agent_BIC")):
                item["creditor_agent_BIC"] = _VALIDATION_BIC_SENTINEL
            if not _s(item.get("debtor_agent_BIC")):
                item["debtor_agent_BIC"] = _VALIDATION_BIC_SENTINEL
            render_rows.append(item)

        xml = generate_xml_string(
            data=render_rows,
            payment_initiation_message_type=MESSAGE_TYPE,
            xml_template_path=template.template_path,
            xsd_schema_path=template.xsd_path,
        )

        # Never expose the internal BIC sentinel. Restore the user's optional
        # fields and validate the exact XML that will be downloaded.
        xml = _clean_optional_xml(xml)
        if not validate_xml_string_via_xsd(xml, template.xsd_path):
            raise RuntimeError("El XML final no supera la validació XSD després d'ometre els camps opcionals buits.")

        return json.dumps({
            "success": True,
            "message_type": MESSAGE_TYPE,
            "xml": xml,
            "rows": len(rows),
            "violations": [],
        })
    except Exception as e:
        return json.dumps({
            "success": False,
            "message_type": MESSAGE_TYPE,
            "violations": [str(e)],
            "rows": len(rows),
        })
