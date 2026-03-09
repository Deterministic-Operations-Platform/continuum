package com.continuum.app

fun main() {
    val service = ProcessingService("continuum-credit-transfer-inbound")
    val handler = RequestHandler(service)
    println(handler.handle("health-check"))
}
