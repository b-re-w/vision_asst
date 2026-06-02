package io.github.brew.visionassist


interface Platform {
    val name: String
}

expect fun getPlatform(): Platform
