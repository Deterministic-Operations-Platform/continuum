package com.continuum.app

fun main() {
    val service = ProcessingService("continuum-gateway")
    val handler = RequestHandler(service)
    println(handler.handle("health-check"))
}
