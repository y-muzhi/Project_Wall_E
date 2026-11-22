/* Native boundary for OC201-ENV-LOCK-1 on a verified Linux filesystem. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/openat2.h>
#include <stdint.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

enum walle_lock_observation {
    WALLE_LOCK_UNHELD = 0,
    WALLE_LOCK_ENTIRE_WRITER = 1,
    WALLE_LOCK_OTHER = 2
};

/* The Python caller validates expected object kind, permissions and identity. */
int walle_env_open_beneath(int root_fd, const char *path, int flags, unsigned int mode)
{
    struct open_how how = {
        .flags = flags | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK,
        .mode = mode,
        .resolve = RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_MAGICLINKS |
                   RESOLVE_NO_XDEV,
    };
    int fd = (int)syscall(SYS_openat2, root_fd, path, &how, sizeof(how));
    return fd < 0 ? -errno : fd;
}

/*
 * The installer supplies the already verified lock-root descriptor.
 * A later fstat against the registered device/inode is mandatory.
 */
int walle_env_lock_open(int lock_root_fd, int writable)
{
    if (writable != 0 && writable != 1)
        return -EINVAL;

    struct open_how how = {
        .flags = (writable ? O_RDWR : O_RDONLY) | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK,
        .resolve = RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_MAGICLINKS |
                   RESOLVE_NO_XDEV,
    };
    int fd = (int)syscall(SYS_openat2, lock_root_fd, "environment.lock", &how, sizeof(how));
    if (fd < 0)
        return -errno;

    struct stat metadata;
    int result = 0;
    if (fstat(fd, &metadata) < 0)
        result = -errno;
    else if (!S_ISREG(metadata.st_mode) || metadata.st_nlink != 1)
        result = -EINVAL;

    if (result < 0) {
        close(fd);
        return result;
    }
    return fd;
}

static struct flock whole_file(short type)
{
    return (struct flock){
        .l_type = type,
        .l_whence = SEEK_SET,
        .l_start = (off_t)0,
        .l_len = (off_t)0,
        .l_pid = (pid_t)0,
    };
}

int walle_env_lock_acquire(int fd)
{
    struct flock range = whole_file(F_WRLCK);
    return fcntl(fd, F_SETLK, &range) == -1 ? -errno : 0;
}

int walle_env_lock_release(int fd)
{
    struct flock range = whole_file(F_UNLCK);
    return fcntl(fd, F_SETLK, &range) == -1 ? -errno : 0;
}

/* Call only from a separate observer. POSIX never reports our own process lock. */
int walle_env_lock_observe(int fd, int64_t *pid)
{
    if (pid == NULL)
        return -EINVAL;
    *pid = 0;
    struct flock range = whole_file(F_WRLCK);
    if (fcntl(fd, F_GETLK, &range) == -1)
        return -errno;
    if (range.l_type == F_UNLCK)
        return WALLE_LOCK_UNHELD;
    if (range.l_type != F_WRLCK || range.l_whence != SEEK_SET ||
        range.l_start != 0 || range.l_len != 0 || range.l_pid <= 0)
        return WALLE_LOCK_OTHER;

    *pid = (int64_t)range.l_pid;
    return WALLE_LOCK_ENTIRE_WRITER;
}
