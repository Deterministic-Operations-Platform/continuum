package com.continuum.app

class ProcessingService(private val serviceName: String) {
    fun process(input: String): String = "$serviceName processed: $input"
}
