import pytest
from investment_assistant.data.identity import stock_id

def test_stock_id_normalizes_us_tickers():
    assert stock_id(' mu ') == 'US:stock:MU'
    assert stock_id('BRK.B') == 'US:stock:BRK.B'

@pytest.mark.parametrize('bad', ['', '600519.SH', '0700.HK', 'ABC.DEF', None])
def test_stock_id_rejects_non_us(bad):
    with pytest.raises(ValueError):
        stock_id(bad)
