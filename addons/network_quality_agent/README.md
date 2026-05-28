# Network Quality Agent Add-on

Dieses Add-on stellt lokal zwei Endpunkte bereit:

- `GET /health`
- `GET /metrics` (kompatibel zur `agent_url`-Erwartung der Integration)

## Standard-URL in der Integration

Wenn in der Integration `agent_mode=addon` gewählt ist und keine `agent_url` gesetzt wird,
verwendet die Integration automatisch:

`http://127.0.0.1:8099/metrics`

## Token-Schutz

Wenn im Add-on ein `token` gesetzt ist, muss die Integration dasselbe `agent_token` setzen.
Die Integration sendet dafür einen Authorization-Header mit Bearer-Token.
