import pytest

from finsight.calc.program import (
    ProgramError,
    execute,
    numbers_match,
    parse_cell,
    parse_program,
)


def test_growth_rate_with_step_reference():
    r = execute("subtract(2.90, 2.60), divide(#0, 2.60)")
    assert r.value == pytest.approx(0.11538, rel=1e-4)
    assert len(r.steps) == 2


def test_percent_literal_is_ratio():
    assert execute("divide(3.8, 1%)").value == pytest.approx(380)


@pytest.mark.parametrize("tok,val", [("const_100", 100), ("const_m1", -1), ("const_1000000", 1e6)])
def test_constants(tok, val):
    assert execute(f"multiply({tok}, const_1)").value == val


def test_negative_values_and_commas():
    assert execute("subtract(-23158, 6427)").value == -29585


def test_greater_returns_yes_no_and_cannot_be_reused():
    assert execute("greater(5, 3)").value == "yes"
    with pytest.raises(ProgramError):
        execute("greater(5, 3), add(#0, 1)")


def test_compound_growth_exp():
    r = execute("divide(const_1, const_5), exp(2, #0)")
    assert r.value == pytest.approx(2 ** 0.2)


TABLE = [
    ["2014", "high", "low"],
    ["first quarter", "$ 62.42", "$ 54.10"],
    ["revenue", "$ 1,200", "$ -300 ( 300 )"],
    ["2013", "high", "low"],
    ["first quarter", "$ 38.02", "$ 34.19"],
]


def test_table_ops_parse_currency_and_negatives():
    assert execute("table_sum(revenue, none)", TABLE).value == 900


def test_ambiguous_row_follows_finqa_and_warns():
    r = execute("table_max(first quarter, none)", TABLE)
    assert r.value == 38.02
    assert r.warnings and r.warnings[0].startswith("ambiguous_row")


@pytest.mark.parametrize("prog", [
    "", "add(1)", "foo(1, 2)", "add(1, 2) garbage", "divide(1, 0)",
    "add(#1, 2)", "table_max(missing, none)",
])
def test_malformed_programs_raise(prog):
    with pytest.raises(ProgramError):
        execute(prog, TABLE)


def test_table_op_without_table_raises():
    with pytest.raises(ProgramError):
        execute("table_max(revenue, none)")


def test_parse_cell():
    assert parse_cell("$ -23158 ( 23158 )") == -23158
    assert parse_cell("12.5%") == pytest.approx(0.125)
    assert parse_cell("n/a") is None


def test_eof_suffix_accepted():
    assert parse_program("add(1, 2), EOF")[0].op == "add"


def test_numbers_match_scale_is_opt_in():
    assert not numbers_match(0.12, 12)
    assert numbers_match(0.12, 12, allow_percent_scale=True)
    assert numbers_match("Yes", "yes")
