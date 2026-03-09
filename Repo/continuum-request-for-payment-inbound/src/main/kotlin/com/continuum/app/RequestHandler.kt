package com.continuum.app

class RequestHandler(private val service: ProcessingService) {
    fun handle(payload: String): String = service.process(payload)
}
