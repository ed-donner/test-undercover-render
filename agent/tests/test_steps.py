"""Every step of the claim agent's work on the claim's page: each lookup and where
it came from, each search of the memory and each save to it, each refusal, and each
call named as its route names it."""

from agent import direct, harness
from agent.gateway import Gateway
from agent.tests.memory_stand_in import MemoryStandIn
from agent.tests.stubs import agent_on, call, decide, stub
from backend.tests.dashboard_reads import steps_of
from context import files

GLOSSARY = files.FILES[files.GLOSSARY]["source"]
MANUAL = files.DOCUMENTS["claims_manual"].source
LOOKUPS = [
    (call("lookup_term", term="unattended"), 'Term "unattended"', ["glossary.yaml"]),
    (call("describe_fields", record="previous_claim"), "Fields of a previous claim",
     ["data_dictionary.yaml"]),
    (call("get_plan", plan="premium"), "Plan: premium", ["plans.yaml"]),
    (call("get_claim_rules"), "The claim rules", ["claim_rules.yaml"]),
    (call("search_reference_data", query="Lisbon strike"),
     'Reference data: "Lisbon strike"', ["reference_data.yaml"]),
    (call("search_reference_data", query="zeppelin"), 'Reference data: "zeppelin"',
     []),
    (call("search_documents", query="unattended"), 'Documents: "unattended"',
     ["policy_wording.md", "claims_manual.md"]),
    (call("read_section", document="claims_manual", number=14),
     "Claims manual, section 14: Records", ["claims_manual.md"]),
]  # fmt: skip


def steps_of_kind(client, claim_id, kind):
    return [s for s in steps_of(client, claim_id) if s["kind"] == kind]


def test_each_context_tool_records_what_it_looked_up_and_where_from(client):
    model = stub(*(reply for reply, _, _ in LOOKUPS), *decide("refer", 0))
    harness.work_claim("CLM-1003", None, agent_on(model))
    lookups = steps_of_kind(client, "CLM-1003", "lookup")
    assert [(s["content"], [f["file"] for f in s["sources"]]) for s in lookups] == [
        (looked_up, files) for _, looked_up, files in LOOKUPS
    ]
    assert lookups[0]["sources"] == [GLOSSARY]
    assert lookups[-1]["sources"] == [MANUAL]


def test_a_memory_search_and_a_save_are_recorded(client):
    store = MemoryStandIn(
        memories=[("/customers/CUS-3005/facts/", "Oliver Grant travels a lot.")]
    )
    model = stub(
        call("search_memory", query="earlier claims"),
        call("search_memory", query="pets"),
        *decide("refer", 0),
    )
    harness.work_claim("CLM-1006", None, agent_on(model, store=store))
    searches = steps_of_kind(client, "CLM-1006", "memory_search")
    assert [s["content"] for s in searches] == [
        '"earlier claims"\n- Oliver Grant travels a lot.',
        '"pets"\n- Oliver Grant travels a lot.',
    ]
    assert all(s["sources"] == [] for s in searches)
    [saved] = steps_of_kind(client, "CLM-1006", "memory_save")
    claimed, decided = (event.message.text for event in store.events)
    assert saved["content"] == f"{claimed}\n{decided}"
    assert steps_of(client, "CLM-1006")[-1] == saved


def test_a_memory_search_that_finds_nothing_says_so(client):
    model = stub(call("search_memory", query="pets"), *decide("refer", 0))
    harness.work_claim("CLM-1006", None, agent_on(model, store=MemoryStandIn()))
    [search] = steps_of_kind(client, "CLM-1006", "memory_search")
    assert search["content"] == '"pets": nothing found'


def test_each_call_is_named_as_its_route_names_it(client, gateway):
    replies = [call("lookup_term", term="unattended"), *decide("refer", 0)]
    harness.work_claim(
        "CLM-1003", None, agent_on(stub(*replies), route=Gateway(gateway.url))
    )
    harness.work_claim(
        "CLM-1004", None, agent_on(stub(*replies), route=direct.from_environment())
    )
    on_the_gateway = [
        s["content"] for s in steps_of_kind(client, "CLM-1003", "tool_call")
    ]
    directly = [s["content"] for s in steps_of_kind(client, "CLM-1004", "tool_call")]
    assert on_the_gateway == [
        'undercover-context___lookup_term(term="unattended")',
        "undercover-app___get_claim()",
        'undercover-app___record_decision(decision="refer", payout=0, '
        'section="Section 3, Trip Delay", reason="The delay was covered.")',
    ]
    assert directly == [
        'lookup_term(term="unattended")',
        "get_claim()",
        'record_decision(decision="refer", payout=0, section="Section 3, Trip Delay", '
        'reason="The delay was covered.")',
    ]
    results = steps_of_kind(client, "CLM-1003", "tool_result")
    assert results[0]["content"].startswith("undercover-context___lookup_term: {")
