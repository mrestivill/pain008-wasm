
import json
import xml.etree.ElementTree as ET

from collections import OrderedDict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from pain001 import (
    generate_xml_string,
    normalize_payment_records,
    validate_scheme,
)
from pain001.xml.message_registry import prepare_xml_data
from jinja2 import select_autoescape
from jinja2.sandbox import SandboxedEnvironment
from pain001.xml.validate_via_xsd import validate_xml_string_via_xsd
from pain001.templates import DEFAULT_TEMPLATE_REGISTRY


MESSAGE_TYPE = "pain.008.001.08"

NS_URI = f"urn:iso:std:iso:20022:tech:xsd:{MESSAGE_TYPE}"
NS = {"p": NS_URI}

ET.register_namespace("", NS_URI)


def _s(value):
    return "" if value is None else str(value).strip()


def _optional(value):
    value = _s(value)
    return value if value else None


def _iso_date(value, field_name, row_number=None):
    text = _s(value)

    if not text:
        return ""

    candidates = [
        text,
        text.replace("/", "-"),
        text.replace(".", "-"),
    ]

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
        f"{field_name}{where} ha de ser una data vàlida "
        f"(YYYY-MM-DD). Valor rebut: {text!r}"
    )


# BIC intern utilitzat exclusivament durant la validació.
# Mai no s'incorpora al XML final.
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

    msg_id = (
        _s(cfg.get("message_id"))
        or "DD" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    )

    default_payment_info_id = (
        _s(cfg.get("payment_info_id"))
        or (msg_id[:30] + "-P1")
    )

    creditor_name = _s(cfg.get("creditor_name"))
    creditor_iban = _s(cfg.get("creditor_iban"))
    creditor_bic = _s(cfg.get("creditor_bic"))
    creditor_scheme_id = _s(cfg.get("creditor_scheme_id"))

    default_collection_date = _s(cfg.get("collection_date"))

    initiator_name = (
        _s(cfg.get("initiator_name"))
        or creditor_name
    )

    for index, src in enumerate(raw_rows, start=1):

        row = {
            str(k).strip().lower(): _s(v)
            for k, v in src.items()
        }

        # PmtInfId pot venir del CSV o de la configuració general.
        # S'accepten les variants habituals del nom del camp.
        payment_info_id = (
            _s(row.get("payment_info_id"))
            or _s(row.get("pmtinfid"))
            or _s(row.get("pmt_inf_id"))
            or default_payment_info_id
        )

        if not payment_info_id:
            raise ValueError(
                f"Fila {index}: PmtInfId és obligatori."
            )

        if len(payment_info_id) > 35:
            raise ValueError(
                f"Fila {index}: PmtInfId supera els 35 caràcters."
            )

        sequence_type = (
            _s(row.get("sequence_type"))
            or default_seq
        )

        payment_id = (
            _s(row.get("payment_id"))
            or f"DD-{index:05d}"
        )

        collection_date = _iso_date(
            _s(row.get("collection_date"))
            or default_collection_date,
            "collection_date",
            index,
        )

        c_name = (
            _s(row.get("creditor_name"))
            or creditor_name
        )

        c_iban = (
            _s(row.get("creditor_account_iban"))
            or _s(row.get("creditor_iban"))
            or creditor_iban
        )

        c_bic = (
            _s(row.get("creditor_agent_bic"))
            or _s(row.get("creditor_bic"))
            or creditor_bic
        )

        c_scheme = (
            _s(row.get("creditor_scheme_id"))
            or creditor_scheme_id
        )

        item = {
            "id": msg_id,
            "message_id": msg_id,
            "date": datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            ),
            "initiator_name": initiator_name,
            "payment_id": payment_id,
            "payment_info_id": payment_info_id,
            "payment_information_id": payment_info_id,
            "end_to_end_id": payment_id,
            "execution_date": collection_date,
            "requested_collection_date": collection_date,
            "creditor_name": c_name,
            "creditor_account_IBAN": c_iban,
            "creditor_scheme_id": c_scheme,
            "debtor_name": _s(row.get("debtor_name")),
            "debtor_account_IBAN": (
                _s(row.get("debtor_iban"))
                or _s(row.get("debtor_account_iban"))
            ),
            "payment_amount": _s(row.get("amount")),
            "payment_currency": (
                _s(row.get("currency"))
                or "EUR"
            ),
            "mandate_id": _s(row.get("mandate_id")),
            "sequence_type": sequence_type,
            "charge_bearer": "SLEV",
        }

        mandate_signed_on = _iso_date(
            _s(row.get("mandate_signed_on"))
            or _s(row.get("mandate_signature_date"))
            or _s(row.get("mandate_date_of_signature")),
            "mandate_signed_on",
            index,
        )

        optional_fields = {
            "creditor_agent_BIC": _optional(c_bic),
            "debtor_agent_BIC": _optional(
                _s(row.get("debtor_bic"))
                or _s(row.get("debtor_agent_bic"))
            ),
            "mandate_signed_on": _optional(mandate_signed_on),
            "remittance_info": _optional(
                _s(row.get("remittance"))
                or _s(row.get("remittance_info"))
            ),
        }

        item.update({
            key: value
            for key, value in optional_fields.items()
            if value is not None
        })

        # Compatibilitat amb les diferents denominacions
        # utilitzades per les plantilles pain001.
        if "mandate_signed_on" in item:
            item["mandate_signature_date"] = item["mandate_signed_on"]
            item["mandate_date_of_signature"] = item["mandate_signed_on"]
            item["date_of_signature"] = item["mandate_signed_on"]

        if "remittance_info" in item:
            item["remittance_information"] = item["remittance_info"]

        if c_bic:
            item["creditor_agent_bic"] = c_bic

        debtor_bic = (
            _s(row.get("debtor_bic"))
            or _s(row.get("debtor_agent_bic"))
        )

        if debtor_bic:
            item["debtor_agent_bic"] = debtor_bic

        out.append(item)

    return out


def _group_rows(rows):
    """
    Agrupa els registres pel seu payment_info_id.
    Manté l'ordre d'aparició al CSV.
    """

    groups = OrderedDict()

    for row in rows:
        payment_info_id = _s(
            row.get("payment_info_id")
            or row.get("payment_information_id")
        )

        groups.setdefault(payment_info_id, []).append(row)

    return groups


def _payment_info_group_violations(rows):
    """
    Comprova que cada PmtInfId tingui una única data
    i les dades comunes del bloc siguin consistents.
    """

    violations = []

    # Camps que han de ser iguals dins d'un mateix PmtInf.
    common_fields = [
        "requested_collection_date",
        "creditor_name",
        "creditor_account_IBAN",
        "creditor_scheme_id",
        "creditor_agent_BIC",
        "sequence_type",
    ]

    for payment_info_id, group in _group_rows(rows).items():

        first = group[0]

        for index, row in enumerate(group[1:], start=2):

            for field in common_fields:

                first_value = _s(first.get(field))
                current_value = _s(row.get(field))

                if first_value != current_value:

                    if field == "requested_collection_date":
                        message = (
                            f"PmtInfId '{payment_info_id}': "
                            f"només pot tenir una data de cobrament. "
                            f"S'han trobat {first_value} i "
                            f"{current_value}."
                        )
                    else:
                        message = (
                            f"PmtInfId '{payment_info_id}': "
                            f"el camp '{field}' té valors diferents "
                            "dins del mateix grup."
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
                        f"Fila {index}: el camp '{field}' "
                        "és obligatori per generar un "
                        "pain.008.001.08 vàlid."
                    ),
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
    payload = json.loads(payload_json)

    rows = _rows_from_payload(payload)

    result, violations = _all_violations(rows)

    has_sequence_column = any(
        "sequence_type" in {
            str(k).strip().lower()
            for k in r.keys()
        }
        for r in payload.get("rows", [])
    )

    return json.dumps({
        "is_valid": (
            bool(getattr(result, "is_valid", False))
            and not violations
        ),
        "rows": len(rows),
        "groups": len(_group_rows(rows)),
        "violations": violations,
        "sequence_type_defaulted_to_ooff": not has_sequence_column,
    })


def _clean_optional_xml(xml):
    """
    Elimina els nodes opcionals buits abans de validar l'XSD.
    """

    root = ET.fromstring(xml)

    for parent_path, tag in [
        (".//p:DbtrAgt/p:FinInstnId", "BICFI"),
        (".//p:CdtrAgt/p:FinInstnId", "BICFI"),
        (".//p:RmtInf", "Ustrd"),
    ]:

        for parent in root.findall(parent_path, NS):

            child = parent.find(f"p:{tag}", NS)

            if child is not None and not _s(child.text):
                parent.remove(child)

                if len(parent) == 0 and parent.tag.endswith("RmtInf"):

                    for tx in root.findall(".//p:DrctDbtTxInf", NS):

                        for rmt in list(tx):
                            if rmt is parent:
                                tx.remove(rmt)

    return ET.tostring(
        root,
        encoding="unicode",
        xml_declaration=True,
    )


def _render_unvalidated_single_group(rows, template):
    """
    Renderitza un únic grup sense executar la validació XSD.
    """

    normalized = normalize_payment_records(rows)

    xml_data = prepare_xml_data(
        normalized,
        MESSAGE_TYPE,
    )

    with open(template.template_path, encoding="utf-8") as handle:
        template_source = handle.read()

    env = SandboxedEnvironment(
        autoescape=select_autoescape(
            enabled_extensions=("xml",),
            default_for_string=True,
        )
    )

    return env.from_string(template_source).render(**xml_data)


def _render_unvalidated_xml(rows, template):
    """
    Genera una previsualització amb tots els grups PmtInf.
    """

    group_xmls = []

    for group in _group_rows(rows).values():
        group_xmls.append(
            _render_unvalidated_single_group(group, template)
        )

    return _merge_group_xml(group_xmls)


def _merge_group_xml(xml_documents):
    """
    Combina els documents generats individualment:
    manté un únic GrpHdr i afegeix tots els PmtInf.
    """

    if not xml_documents:
        raise ValueError("No hi ha documents XML per combinar.")

    first_root = ET.fromstring(xml_documents[0])

    first_init = first_root.find(
        "p:CstmrDrctDbtInitn",
        NS,
    )

    if first_init is None:
        raise RuntimeError("No s'ha trobat CstmrDrctDbtInitn.")

    first_header = first_init.find("p:GrpHdr", NS)

    if first_header is None:
        raise RuntimeError("No s'ha trobat GrpHdr.")

    for xml in xml_documents[1:]:

        root = ET.fromstring(xml)

        init = root.find(
            "p:CstmrDrctDbtInitn",
            NS,
        )

        if init is None:
            raise RuntimeError("Un grup no conté CstmrDrctDbtInitn.")

        header = init.find("p:GrpHdr", NS)

        if header is None:
            raise RuntimeError("Un grup no conté GrpHdr.")

        # Comprovar que tots els documents pertanyen
        # al mateix missatge.
        for tag in ["MsgId", "InitgPty"]:
            first_value = ET.tostring(
                first_header.find(f"p:{tag}", NS),
                encoding="unicode",
            )

            current_value = ET.tostring(
                header.find(f"p:{tag}", NS),
                encoding="unicode",
            )

            if first_value != current_value:
                raise RuntimeError(
                    f"El camp GrpHdr/{tag} no coincideix "
                    "entre els grups."
                )

        for pmt in init.findall("p:PmtInf", NS):
            first_init.append(pmt)

    # Recalcular els totals globals a partir dels blocs PmtInf.
    all_pmts = first_init.findall("p:PmtInf", NS)

    total_transactions = 0
    total_amount = Decimal("0.00")

    for pmt in all_pmts:

        count = pmt.findtext("p:NbOfTxs", namespaces=NS)

        if count:
            total_transactions += int(count)

        amount = pmt.findtext("p:CtrlSum", namespaces=NS)

        if amount:
            try:
                total_amount += Decimal(amount)
            except InvalidOperation:
                raise RuntimeError(
                    f"CtrlSum no vàlid dins de PmtInf: {amount}"
                )

    header_count = first_header.find("p:NbOfTxs", NS)

    if header_count is not None:
        header_count.text = str(total_transactions)

    header_sum = first_header.find("p:CtrlSum", NS)

    if header_sum is not None:
        header_sum.text = f"{total_amount:.2f}"

    return ET.tostring(
        first_root,
        encoding="unicode",
        xml_declaration=True,
    )


def _generate_group_xml(rows, template):
    """
    Genera un XML individual per a un grup PmtInf.
    """

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

    return _clean_optional_xml(xml)


def _verify_payment_info_groups(xml, rows):
    """
    Comprova que els PmtInf del XML coincideixin amb
    els grups i dates esperats.
    """

    root = ET.fromstring(xml)

    expected = {}

    for payment_info_id, group in _group_rows(rows).items():

        expected[payment_info_id] = (
            _s(group[0].get("requested_collection_date")),
            len(group),
        )

    actual = {}

    init = root.find("p:CstmrDrctDbtInitn", NS)

    if init is None:
        raise RuntimeError("No s'ha trobat CstmrDrctDbtInitn.")

    for pmt in init.findall("p:PmtInf", NS):

        pid = pmt.findtext(
            "p:PmtInfId",
            namespaces=NS,
        )

        collection_date = pmt.findtext(
            "p:ReqdColltnDt",
            namespaces=NS,
        )

        count = pmt.findtext(
            "p:NbOfTxs",
            namespaces=NS,
        )

        if not pid:
            raise RuntimeError("S'ha generat un PmtInf sense PmtInfId.")

        if pid in actual:
            raise RuntimeError(
                f"El PmtInfId '{pid}' apareix duplicat al XML."
            )

        actual[pid] = (
            collection_date,
            int(count or 0),
        )

    if expected != actual:
        raise RuntimeError(
            "Els blocs PmtInf generats no coincideixen "
            f"amb els esperats. Esperats: {expected}. "
            f"Generats: {actual}."
        )

    # Comprovar també els totals globals.
    header = init.find("p:GrpHdr", NS)

    if header is None:
        raise RuntimeError("No s'ha trobat GrpHdr.")

    header_count = header.findtext(
        "p:NbOfTxs",
        namespaces=NS,
    )

    expected_count = len(rows)

    if int(header_count or 0) != expected_count:
        raise RuntimeError(
            f"NbOfTxs global incorrecte: {header_count}. "
            f"S'esperaven {expected_count}."
        )


def generate(payload_json):
    payload = json.loads(payload_json)

    rows = _rows_from_payload(payload)

    schema_template = DEFAULT_TEMPLATE_REGISTRY.get_template(
        MESSAGE_TYPE
    )

    if schema_template is None:
        return json.dumps({
            "success": False,
            "violations": [
                f"No s'ha trobat l'XSD per a {MESSAGE_TYPE}."
            ],
            "rows": len(rows),
        })

    try:
        custom_template_source = _load_custom_template()
    except Exception as e:
        return json.dumps({
            "success": False,
            "violations": [str(e)],
            "rows": len(rows),
        })

    try:

        result, violations = _all_violations(rows)

    except Exception as e:

        try:
            preview = _render_unvalidated_xml(rows, schema_template)
        except Exception as render_error:
            preview = ""
            error = (
                f"{e}; previsualització XML: {render_error}"
            )
        else:
            error = str(e)

        return json.dumps({
            "success": False,
            "violations": [error],
            "xml_preview": preview,
            "rows": len(rows),
        })

    if not getattr(result, "is_valid", False) or violations:

        try:
            preview = _render_unvalidated_xml(rows, schema_template)
        except Exception as render_error:
            preview = ""
            violations.append(
                f"No s'ha pogut renderitzar la previsualització XML: "
                f"{render_error}"
            )

        return json.dumps({
            "success": False,
            "violations": violations,
            "xml_preview": preview,
            "rows": len(rows),
        })

    try:

        # Generar un document XML per cada PmtInfId.
        group_xmls = []

        for group in _group_rows(rows).values():

            group_xml = _generate_group_xml(
                group,
                template,
            )

            group_xmls.append(group_xml)

        # Combinar tots els blocs en un únic fitxer XML.
        xml = _merge_group_xml(group_xmls)

        # Comprovar identificadors, dates i comptadors.
        _verify_payment_info_groups(xml, rows)

        # Validar el document XML complet.
        if not validate_xml_string_via_xsd(
            xml,
            template.xsd_path,
        ):
            raise RuntimeError(
                "El XML final no supera la validació XSD."
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

    except Exception as e:

        preview = ""

        try:
            preview = _render_unvalidated_xml(
                rows,
                template,
            )
        except Exception as render_error:
            error_text = (
                f"{e}; previsualització XML: {render_error}"
            )
        else:
            error_text = str(e)

        return json.dumps({
            "success": False,
            "message_type": MESSAGE_TYPE,
            "violations": [error_text],
            "xml_preview": preview,
            "rows": len(rows),
            "groups": len(_group_rows(rows)),
        })
