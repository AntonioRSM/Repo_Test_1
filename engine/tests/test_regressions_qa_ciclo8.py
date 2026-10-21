"""Test di regressione del ciclo QA 8 (Bug #31).

Il filtro su -EncodedCommand si aggirava ancora con l'accento grave (carattere di
escape di PowerShell, ignorato davanti alle lettere senza significato speciale),
con l'operatore punto (dot-source, che avvia un programma come &) e con cmd
richiamato tramite $env:ComSpec.
"""

import pytest

from vault_engine.agent import tools as agent_tools


@pytest.mark.parametrize(
    "cmd",
    [
        "power`shell -e SGVsbG8=",  # accento grave nel nome del comando
        "powershell -e`nc SGVsbG8=",  # accento grave nello switch: `n è un a capo
        ". powershell -e SGVsbG8=",  # operatore punto (dot-source) come &
        "& $env:ComSpec /c powershell -e SGVsbG8=",  # cmd tramite variabile d'ambiente
        "$env:ComSpec /c powershell -enc SGVsbG8=",  # variante senza &
    ],
)
def test_encoded_filter_bypass_cycle8_blocked(cmd):
    """Bug #31: le 4 forme di aggiramento del ciclo 8 vanno bloccate."""
    assert agent_tools._uses_encoded_command(cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        '. .\\script\\legittimo.ps1',  # dot-source di uno script normale
        "& $env:ComSpec /c dir",  # $env:ComSpec senza powershell codificato
        "Write-Host \"riga1`nriga2\"",  # `n legittimo in una stringa
        "Write-Host '100`% fatto'",  # accento grave davanti a un simbolo
        "powershell -File script.ps1 -Verbose",  # uso legittimo di powershell
    ],
)
def test_encoded_filter_cycle8_no_false_positives(cmd):
    """Bug #31: la deoffuscazione non deve bloccare i comandi legittimi."""
    assert not agent_tools._uses_encoded_command(cmd)
