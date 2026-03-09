package com.continuum.app

fun main() {
    val service = ProcessingService("continuum-request-for-payment-outbound")
    val handler = RequestHandler(service)
    println(handler.handle("health-check"))
}
