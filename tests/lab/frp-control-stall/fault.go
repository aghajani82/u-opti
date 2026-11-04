// Test-only fault injection. Never built into a released image or binary.
// The real sticky crypto writer behavior is independently covered by the
// unmodified upstream handler_write_error_test.go regression.
package server

import (
    "errors"
    "os"
    "github.com/fatedier/frp/pkg/msg"
)

type uoptiFault struct {
    *msg.Conn
    target bool
    failed bool // WriteMsg has one owner: Dispatcher.sendLoop.
}
func uoptiFaultConn(conn *msg.Conn, user string) msg.ReadWriter {
    return &uoptiFault{Conn:conn, target:user == "lab-a"}
}
func (c *uoptiFault) WriteMsg(m msg.Message) error {
    if c.target {
        if _, ok := m.(*msg.ReqWorkConn); ok && !c.failed {
            marker := os.Getenv("UOPTI_FRP_LAB_FAULT")
            if marker != "" && os.Rename(marker, marker+".fired") == nil {
                c.failed = true
            }
        }
        if c.failed { return errors.New("injected retained control write timeout") }
    }
    return c.Conn.WriteMsg(m)
}
