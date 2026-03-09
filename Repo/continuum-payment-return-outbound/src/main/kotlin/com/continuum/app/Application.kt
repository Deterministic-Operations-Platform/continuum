package com.continuum.app

fun main() {
    val service = ProcessingService("continuum-payment-return-outbound")
    val handler = RequestHandler(service)
    println(handler.handle("health-check"))
}
