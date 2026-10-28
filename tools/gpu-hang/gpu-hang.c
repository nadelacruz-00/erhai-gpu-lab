// SPDX-License-Identifier: GPL-2.0-only
/*
 * gpu-hang: deliberately keep the GPU busy with one long fragment-shader
 * loop, to provoke (and time) hang detection and recovery.
 *
 * WARNING: on a kernel whose GPU hang recovery is broken, a large
 * --iterations value freezes the display until a hard reset. Use
 * --iterations 1 for smoke tests. The default is deliberately huge.
 */
#define _GNU_SOURCE
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <GLES2/gl2ext.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define EXIT_COMPLETED 0
#define EXIT_SETUP     2
#define EXIT_RESET     3
#define EXIT_TIMEOUT   4
#define WATCHDOG_SECS  20

static atomic_int finished;
static unsigned long long g_iters;
static struct timespec t0;

static double elapsed(void)
{
	struct timespec t;

	clock_gettime(CLOCK_MONOTONIC, &t);
	return (t.tv_sec - t0.tv_sec) + (t.tv_nsec - t0.tv_nsec) / 1e9;
}

static void report(const char *result)
{
	printf("gpu-hang: iterations=%llu result=%s elapsed=%.3f\n",
	       g_iters, result, elapsed());
	fflush(stdout);
}

static void *watchdog(void *arg)
{
	(void)arg;
	for (int i = 0; i < WATCHDOG_SECS * 100; i++) {
		usleep(10000);
		if (atomic_load(&finished))
			return NULL;
	}
	if (!atomic_load(&finished)) {
		report("timeout");
		_exit(EXIT_TIMEOUT);
	}
	return NULL;
}

static void usage(const char *argv0)
{
	fprintf(stderr,
		"usage: %s [--iterations N]\n"
		"  Runs one fragment-shader loop of N iterations (default 0xFFFFFFFF,\n"
		"  which hangs the GPU). Use --iterations 1 for a safe smoke test.\n"
		"exit codes:\n"
		"  0  draw completed, no reset reported\n"
		"  2  setup failure (usage, EGL, GLES, shader compile/link)\n"
		"  3  GPU reset detected (GL_KHR_robustness)\n"
		"  4  glFinish still blocked after %d s (watchdog)\n",
		argv0, WATCHDOG_SECS);
}

static int fail(const char *what)
{
	fprintf(stderr, "gpu-hang: %s\n", what);
	return EXIT_SETUP;
}

static const char *vs_src =
	"#version 300 es\n"
	"in vec2 p;\n"
	"void main() { gl_Position = vec4(p, 0.0, 1.0); }\n";

/* The accumulator feeds the colour, so the loop cannot be elided. */
static const char *fs_src =
	"#version 300 es\n"
	"precision highp float;\n"
	"uniform uint u_iters;\n"
	"out vec4 o;\n"
	"void main() {\n"
	"  float a = gl_FragCoord.x * 0.001;\n"
	"  for (uint i = 0u; i < u_iters; i++)\n"
	"    a = fract(a * 1.0001 + float(i & 255u) * 0.0001);\n"
	"  o = vec4(a, a, a, 1.0);\n"
	"}\n";

static GLuint compile(GLenum type, const char *src)
{
	GLuint s = glCreateShader(type);
	GLint ok = 0;

	glShaderSource(s, 1, &src, NULL);
	glCompileShader(s);
	glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
	if (!ok) {
		char log[512];

		glGetShaderInfoLog(s, sizeof(log), NULL, log);
		fprintf(stderr, "gpu-hang: shader compile failed: %s\n", log);
		return 0;
	}
	return s;
}

int main(int argc, char **argv)
{
	g_iters = 0xFFFFFFFFULL;
	for (int i = 1; i < argc; i++) {
		if (!strcmp(argv[i], "--iterations") && i + 1 < argc) {
			char *end;

			g_iters = strtoull(argv[++i], &end, 0);
			if (*end || g_iters > 0xFFFFFFFFULL) {
				usage(argv[0]);
				return EXIT_SETUP;
			}
		} else {
			usage(argv[0]);
			return strcmp(argv[i], "--help") ? EXIT_SETUP : 0;
		}
	}

	setenv("EGL_PLATFORM", "surfaceless", 0);

	EGLDisplay dpy = EGL_NO_DISPLAY;
	PFNEGLGETPLATFORMDISPLAYEXTPROC getpd =
		(PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
	if (getpd)
		dpy = getpd(EGL_PLATFORM_SURFACELESS_MESA, EGL_DEFAULT_DISPLAY, NULL);
	if (dpy == EGL_NO_DISPLAY)
		dpy = eglGetDisplay(EGL_DEFAULT_DISPLAY);
	if (dpy == EGL_NO_DISPLAY || !eglInitialize(dpy, NULL, NULL))
		return fail("eglInitialize failed");
	if (!eglBindAPI(EGL_OPENGL_ES_API))
		return fail("eglBindAPI failed");

	const char *eglext = eglQueryString(dpy, EGL_EXTENSIONS);
	int robust_ctx = eglext && strstr(eglext, "EGL_EXT_create_context_robustness");
	EGLint cfg_attr[] = { EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT,
			      EGL_SURFACE_TYPE, 0, EGL_NONE };
	EGLConfig cfg;
	EGLint ncfg = 0;

	if (!eglChooseConfig(dpy, cfg_attr, &cfg, 1, &ncfg) || !ncfg) {
		cfg_attr[1] = EGL_OPENGL_ES2_BIT;	/* ES3 contexts are made from ES2-bit configs on some drivers */
		if (!eglChooseConfig(dpy, cfg_attr, &cfg, 1, &ncfg) || !ncfg)
			return fail("no usable EGL config");
	}
	EGLint ctx_attr[] = { EGL_CONTEXT_CLIENT_VERSION, 3,
			      EGL_CONTEXT_OPENGL_RESET_NOTIFICATION_STRATEGY_EXT,
			      EGL_LOSE_CONTEXT_ON_RESET_EXT, EGL_NONE };
	EGLContext ctx = eglCreateContext(dpy, cfg, EGL_NO_CONTEXT,
					  robust_ctx ? ctx_attr : (EGLint[]){ EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE });
	if (ctx == EGL_NO_CONTEXT)
		return fail("eglCreateContext (GLES 3.0) failed");
	if (!eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, ctx))
		return fail("eglMakeCurrent (surfaceless) failed");

	const char *glext = (const char *)glGetString(GL_EXTENSIONS);
	PFNGLGETGRAPHICSRESETSTATUSKHRPROC get_reset = NULL;
	if (glext && strstr(glext, "GL_KHR_robustness"))
		get_reset = (PFNGLGETGRAPHICSRESETSTATUSKHRPROC)eglGetProcAddress("glGetGraphicsResetStatusKHR");

	GLuint tex, fbo;

	glGenTextures(1, &tex);
	glBindTexture(GL_TEXTURE_2D, tex);
	glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 64, 64, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
	glGenFramebuffers(1, &fbo);
	glBindFramebuffer(GL_FRAMEBUFFER, fbo);
	glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, 0);
	if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE)
		return fail("64x64 FBO incomplete");
	glViewport(0, 0, 64, 64);

	GLuint vs = compile(GL_VERTEX_SHADER, vs_src);
	GLuint fs = compile(GL_FRAGMENT_SHADER, fs_src);
	if (!vs || !fs)
		return EXIT_SETUP;
	GLuint prog = glCreateProgram();
	GLint ok = 0;

	glAttachShader(prog, vs);
	glAttachShader(prog, fs);
	glBindAttribLocation(prog, 0, "p");
	glLinkProgram(prog);
	glGetProgramiv(prog, GL_LINK_STATUS, &ok);
	if (!ok)
		return fail("program link failed");
	glUseProgram(prog);
	glUniform1ui(glGetUniformLocation(prog, "u_iters"), (GLuint)g_iters);

	static const GLfloat quad[] = { -1, -1, 1, -1, -1, 1, 1, 1 };

	glEnableVertexAttribArray(0);
	glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, quad);

	pthread_t wd;

	clock_gettime(CLOCK_MONOTONIC, &t0);
	if (pthread_create(&wd, NULL, watchdog, NULL))
		return fail("cannot start watchdog thread");
	glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
	glFinish();
	atomic_store(&finished, 1);
	pthread_join(wd, NULL);

	if (get_reset && get_reset() != GL_NO_ERROR) {
		report("reset");
		return EXIT_RESET;
	}
	if (glGetError() != GL_NO_ERROR)
		return fail("GL error after draw");
	report("completed");
	return EXIT_COMPLETED;
}
