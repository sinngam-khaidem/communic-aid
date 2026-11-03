import ARKit
import CoreImage
import UIKit

/// Renders a tiny picture of the camera image with ARKit's face landmarks drawn on it,
/// for the small corner window on the Mac. Nothing is shown on the phone itself.
///
/// One job only: frame in, small JPEG out. FaceSensor decides how often to ask.
final class FacePreview {
    let size = CGSize(width: 120, height: 160)
    private let context = CIContext()
    private let format: UIGraphicsImageRendererFormat = {
        let f = UIGraphicsImageRendererFormat()
        f.scale = 1
        return f
    }()

    func jpeg(frame: ARFrame, face: ARFaceAnchor?) -> Data? {
        guard let picture = cameraImage(frame) else { return nil }
        let image = UIGraphicsImageRenderer(size: size, format: format).image { ctx in
            picture.draw(in: CGRect(origin: .zero, size: size))
            if let face { drawLandmarks(ctx.cgContext, frame: frame, face: face) }
        }
        return image.jpegData(compressionQuality: 0.5)
    }

    /// The camera image as the phone would display it in portrait, scaled down to `size`.
    private func cameraImage(_ frame: ARFrame) -> UIImage? {
        let buffer = frame.capturedImage
        let imageSize = CGSize(width: CVPixelBufferGetWidth(buffer), height: CVPixelBufferGetHeight(buffer))
        let normalize = CGAffineTransform(scaleX: 1 / imageSize.width, y: 1 / imageSize.height)
        let flip = CGAffineTransform(scaleX: -1, y: -1).translatedBy(x: -1, y: -1)
        let display = frame.displayTransform(for: .portrait, viewportSize: size)
        let toView = CGAffineTransform(scaleX: size.width, y: size.height)
        let image = CIImage(cvPixelBuffer: buffer)
            .transformed(by: normalize.concatenating(flip).concatenating(display).concatenating(toView))
        guard let cg = context.createCGImage(image, from: CGRect(origin: .zero, size: size)) else { return nil }
        return UIImage(cgImage: cg)
    }

    /// The face mesh as fine dots, and the two eye centres in pink.
    private func drawLandmarks(_ g: CGContext, frame: ARFrame, face: ARFaceAnchor) {
        let project = { (world: SIMD3<Float>) -> CGPoint in
            frame.camera.projectPoint(world, orientation: .portrait, viewportSize: self.size)
        }
        g.setFillColor(UIColor(red: 0.37, green: 0.75, blue: 0.75, alpha: 0.85).cgColor)
        let vertices = face.geometry.vertices
        for i in stride(from: 0, to: vertices.count, by: 4) {
            let p = project((face.transform * SIMD4<Float>(vertices[i], 1)).xyz3)
            g.fillEllipse(in: CGRect(x: p.x - 0.6, y: p.y - 0.6, width: 1.2, height: 1.2))
        }
        g.setFillColor(UIColor(red: 1.0, green: 0.40, blue: 0.59, alpha: 1).cgColor)
        for eye in [face.leftEyeTransform, face.rightEyeTransform] {
            let p = project((face.transform * eye).columns.3.xyz3)
            g.fillEllipse(in: CGRect(x: p.x - 2.5, y: p.y - 2.5, width: 5, height: 5))
        }
    }
}

private extension SIMD4 where Scalar == Float {
    var xyz3: SIMD3<Float> { SIMD3(x, y, z) }
}
