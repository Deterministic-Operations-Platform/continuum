package com.continuum.app

fun main() {
    val service = ProcessingService("continuum-payment-return-inbound")
    val handler = RequestHandler(service)
    println(handler.handle("health-check"))
}
