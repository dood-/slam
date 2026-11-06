"""Canonical camera pose contract: camera-to-world, quaternion XYZW."""
import numpy as np


def normalize_camera_pose(rotation, translation):
    """Invert a COLMAP world-to-camera pose without changing world axes."""
    rotation = np.asarray(rotation, dtype=float).reshape(3, 3)
    translation = np.asarray(translation, dtype=float).reshape(3)
    if not np.isfinite(rotation).all() or not np.isfinite(translation).all():
        raise ValueError('Non-finite camera pose')
    inverse = rotation.T
    # Stable matrix-to-quaternion conversion; quaternion order is explicitly XYZW.
    trace = np.trace(inverse)
    if trace > 0:
        scale = np.sqrt(trace + 1) * 2
        quat = np.array([(inverse[2,1]-inverse[1,2])/scale,
                         (inverse[0,2]-inverse[2,0])/scale,
                         (inverse[1,0]-inverse[0,1])/scale, scale/4])
    else:
        i = int(np.argmax(np.diag(inverse)))
        j, k = (i+1)%3, (i+2)%3
        scale = np.sqrt(max(0, 1+inverse[i,i]-inverse[j,j]-inverse[k,k])) * 2
        quat = np.zeros(4)
        quat[i] = scale/4
        quat[j] = (inverse[j,i]+inverse[i,j])/scale
        quat[k] = (inverse[k,i]+inverse[i,k])/scale
        quat[3] = (inverse[k,j]-inverse[j,k])/scale
    quat /= np.linalg.norm(quat)
    return -inverse @ translation, quat
