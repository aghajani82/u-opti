// Test fixture copied into upstream pkg/config/v1; no production config change.
package v1
import "testing"
func TestUoptiGeneratedWSSDefaults(t *testing.T) {
    c:=ClientTransportConfig{Protocol:"wss"}
    c.Complete()
    s:=ServerTransportConfig{}
    s.Complete()
    if c.TCPMux == nil || !*c.TCPMux || s.TCPMux == nil || !*s.TCPMux {
        t.Fatal("unexpected mux defaults")
    }
    if c.HeartbeatInterval != -1 || c.HeartbeatTimeout != -1 || s.HeartbeatTimeout != -1 {
        t.Fatalf("heartbeat differs: %d %d %d", c.HeartbeatInterval,c.HeartbeatTimeout,s.HeartbeatTimeout)
    }
    if c.WireProtocol != "v1" || c.TCPMuxKeepaliveInterval != 30 || s.TCPMuxKeepaliveInterval != 30 {
        t.Fatal("wire or mux keepalive defaults differ")
    }
    t.Logf("wss: wire=%s mux=true keepalive=%d clientHeartbeat=%d/%d serverHeartbeat=%d pool=%d",
        c.WireProtocol,c.TCPMuxKeepaliveInterval,c.HeartbeatInterval,c.HeartbeatTimeout,s.HeartbeatTimeout,c.PoolCount)
}
