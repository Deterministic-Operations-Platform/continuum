package com.continuum.app

fun main() {
    val service = ProcessingService("continuum-common")
    val handler = RequestHandler(service)
    println(handler.handle("health-check"))
}
