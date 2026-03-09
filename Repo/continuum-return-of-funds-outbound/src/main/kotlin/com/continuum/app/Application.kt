package com.continuum.app

fun main() {
    val service = ProcessingService("continuum-return-of-funds-outbound")
    val handler = RequestHandler(service)
    println(handler.handle("health-check"))
}
