package com.continuum.app

fun main() {
    val service = ProcessingService("continuum-integrations")
    val handler = RequestHandler(service)
    println(handler.handle("health-check"))
}
