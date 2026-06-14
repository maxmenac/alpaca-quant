// Command executor is the (future) OMS entrypoint. In this sprint it only announces the
// paper-first posture; there is no broker client and no live trading.
package main

import "fmt"

func main() {
	fmt.Println("Alpaca Quant Executor — paper-first, no live trading enabled")
}
